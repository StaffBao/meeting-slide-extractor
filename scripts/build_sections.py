# build_sections.py  (V2.2.0)
# Detect presentation "sections" (讲者场次) from a recording, so the HTML viewer,
# the sectioned PPTX and the transcript can all carry the same 【节】 markers.
#
# WHY a dedicated step: the raw ASR stream has no notion of who is talking.
# Instead of speaker diarization (heavy: ~2GB deps, hours on CPU), we exploit two
# cheap and — on training recordings — very regular signals:
#   1. the host's hand-over formulas  "有请…老师" / "谢谢…老师"
#   2. the speaker's own title slide (题目 + 姓名), found via slide OCR
#
# RULES (agreed with the user):
#   * a hand-over must name a SPECIFIC person to count as a boundary.
#     Generic thanks ("谢谢大家" / "感谢各位") are the speaker's own words, not a
#     boundary — measured false positive at 1:45:24 in the reference recording.
#   * the same hand-over sentence can appear twice (mic test / false start). Keep
#     the occurrence whose slide text actually matches it.
#   * time→page mapping lands on the PREVIOUS slide (the host speaks before the
#     speaker advances). So search FORWARD for the speaker's title slide.
#   * names on the slide win over names in the transcript. ASR mis-hears names
#     (measured: 蒲一虎 vs slide 浦义虎; 史兰 vs slide 史岚). ASR also glues the
#     invitation verb onto the name ("有请杨阳", "心徐建龙", "请蒲一虎") — so the
#     name is matched only AFTER the invitation verb.
#   * 开班动员/致辞 is its own section kind ("opening"), because its hand-over
#     sentence often names an organisation instead of a person.
#   * 问答 / 点评 are separate section kinds when they occur.
#
# Usage:
#   python build_sections.py --meta slides_meta.json --asr output/asr_transcript.txt \
#       --ocr output/slides_ocr.txt --out output/sections.json \
#       [--log output/sections_log.md] [--deck-title "..."] [--override ov.json]
import argparse, bisect, json, os, re, datetime

CJK = r"\u4e00-\u9fa5"
TITLES = ("老师", "处长", "主任", "教授", "医师", "专家", "院长", "主席", "秘书长", "校长", "部长", "司长", "局长")
TITLE_ALT = "|".join(TITLES)

# words that look like a "name" to a regex but are not people
NOT_A_NAME = {
    "各位", "大家", "你们", "我们", "他们", "所有", "线上", "与会", "本次",
    "中心", "药监", "药品", "监督", "管理", "上海", "上海市", "研究", "监测",
    "精彩", "热情", "辛苦", "精心", "支持", "帮助", "分享", "讲解", "报告",
    "主持", "致辞", "动员", "内容", "主题", "议题", "专家", "领导",
}

# a slide that introduces a speaker usually carries one of these
TITLE_PAGE_HINTS = re.compile(r"汇报人|主讲人|报告人|讲者|演讲人|作\s*者|分享人")
NAME_LINE = re.compile(r"^([" + CJK + r"]{2,4})$")
# "汇报人：徐建龙" / "主讲人 杨阳"
NAME_AFTER_LABEL = re.compile(r"(?:汇报人|主讲人|报告人|讲者|演讲人|分享人|作者)\s*[:：]?\s*([" + CJK + r"]{2,4})")

# A greedy `[CJK]{2,4}` before a courtesy title slides its left edge into the
# preceding word and fabricates names — measured on the reference recording:
#   "药品监管处史兰处长"  -> "管处史兰"
#   "监测中心徐建龙老师"  -> "心徐建龙"
#   "有请杨阳老师"        -> "有请杨阳"
# The fix is the standard Chinese-NER heuristic: a personal name STARTS WITH A
# SURNAME. Among all candidates ending at the title, prefer a surname-initial
# one, then the shortest (2-3 char names dominate; 4+ is usually swallowed text).
SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏窦章"
    "云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安"
    "常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋"
    "茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊"
    "胡凌霍虞万支柯昝管卢莫房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀"
    "羊惠甄封储靳段富巫乌焦巴弓牧山谷车侯全班仰秋仲伊宫宁仇栾暴甘厉戎祖武符刘景詹束"
    "龙叶幸司韶黎薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔胥苍双闻莘党翟谭贡劳姬申扶堵"
    "冉宰郦雍桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎充慕连茹习艾鱼容向古易慎戈廖庾"
    "终居衡步都耿满弘匡国文寇广东欧沃利蔚越聂晁勾敖融冷辛阚那简饶空曾沙养鞠须丰巢关"
    "查后荆红游竺权盖益桓公欧阳司马上官诸葛夏侯皇甫尉迟长孙宇文司徒司空公孙慕容贺兰"
    "令狐独孤南宫东方轩辕闻人赫连澹台公冶宗政濮阳太叔申屠仲孙钟离鲜于闾丘子车颛孙"
)
# morphemes that betray a swallowed organisation/department word
ORG_MORPHEME = re.compile(r"中心|管处|监管|管理|监督|监测|药品|器械|不良|反应|办公|"
                          r"处|局|科|司|部|室|站|所|会|站|委|组|办|班|组")


def _name_score(cand, start_idx):
    """(-surname_first, length) — lower is better."""
    return (0 if cand[0] in SURNAMES else 1, len(cand), start_idx)


def best_name(text):
    """Best personal-name candidate in `text`, or None.

    Collects every `name+title` match and keeps the surname-initial, shortest
    one, which is what defeats the swallowed-prefix failures above.

    A zero-width lookahead is required: `re.finditer` returns NON-overlapping
    matches, so a plain greedy scan would consume "感谢史兰处长" in one bite and
    never offer the correct two-character "史兰" as a candidate.
    """
    if not text:
        return None
    cands = []
    pat = re.compile(r"(?=([" + CJK + r"]{2,4})(?:" + TITLE_ALT + r"))")
    for m in pat.finditer(text):
        cand = m.group(1)
        if cand in NOT_A_NAME or ORG_MORPHEME.search(cand):
            continue
        cands.append((_name_score(cand, m.start()), cand))
    if not cands:
        return None
    return min(cands)[1]
# organisation / bureau footer, never a talk title
ORG_WORDS = re.compile(r"上海市|上海|药品|医疗器械|不良反应|监测|监督管理|监督管理局|中心|局|处|科|公司|大学|学院|医院|研究院|学会|协会")
# a footer/attribution line: short AND ending in an org suffix. Using a
# substring test instead would wrongly drop legitimate title words such as
# "共同筑牢药品安全防线" (contains 药品).
ORG_FOOTER = re.compile(r"(局|中心|处|科|室|公司|协会|学会|医院|大学|学院|研究院|委员会|处长|科长|主任|主席)$")

# Tencent-Meeting / recorder overlays that get burned into the frames
UI_NOISE = re.compile(r"共享屏幕|屏幕共享|监测中心的屏幕|正在共享|会议中|录制")
# recurring poster furniture of this event's template
SHELL_LINES = {
    "上海", "上", "海", "阳光政务·公开为民", "阳光政务", "政府开放月", "沪药法治",
    "目录", "目", "录", "CONTENTS", "Contents", "contents", "谢谢聆听", "感谢聆听",
    "谢谢观看", "汇报人", "时间", "总结与展望",
}
DATE_ONLY = re.compile(r"^[\d\s年.\-/月日:：]+$")


def parse_asr(path):
    """-> [{'t': float, 'txt': str}]"""
    out = []
    pat = re.compile(r"^\[(\d+):(\d+):(\d+)[,.](\d+)\]\s*(.*)$")
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = pat.match(line.strip())
            if not m:
                continue
            h, mi, s, ms, txt = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000.0
            if txt.strip():
                out.append({"t": t, "txt": txt.strip()})
    return out


def parse_ocr(path):
    """-> {n: text}  (section header '# 第 NNN 页')"""
    if not path or not os.path.exists(path):
        return {}
    out, cur, buf = {}, None, []
    pat = re.compile(r"^#\s*第\s*0*(\d+)\s*页")
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = pat.match(line)
            if m:
                if cur is not None:
                    out[cur] = "\n".join(buf).strip()
                cur, buf = int(m.group(1)), []
            else:
                buf.append(line.rstrip("\n"))
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def page_at(meta, ts):
    """largest n whose t <= ts"""
    arr = [m["t"] for m in meta]
    i = bisect.bisect_right(arr, ts) - 1
    return meta[max(i, 0)]["n"] if meta else None


# ---------------------------------------------------------------- hand-overs
INVITE = re.compile(r"有请|下面请|接下来请|请出|欢迎")
THANKS = re.compile(r"(?:谢谢|感谢)\s*(?P<name>[" + CJK + r"]{2,4})\s*(?:" + TITLE_ALT + r")")
OPENING = re.compile(r"开班动员|致辞|开幕|致欢迎辞")


def name_in(text):
    """First plausible personal name followed by a courtesy title, or None.

    The match starts AFTER any invitation/thanks verb, otherwise the greedy name
    group swallows the verb itself (measured: 有请杨阳 / 心徐建龙 / 请蒲一虎).
    """
    text = text or ""
    m0 = INVITE.search(text)
    if m0:
        text = text[m0.end():]
    return best_name(text)


def find_handovers(segments):
    """Candidate boundaries. Invitations count even without a name (opening)."""
    ev = []
    for i, s in enumerate(segments):
        txt = s["txt"]
        m = INVITE.search(txt)
        if m:
            tail = txt[m.end():]
            nm = name_in(tail)
            if nm is None:
                # the host often spills the name into the next caption
                for s2 in segments[i + 1:i + 3]:
                    nm = name_in(s2["txt"])
                    if nm:
                        break
            ctx = " ".join([txt] + [x["txt"] for x in segments[i + 1:i + 3]])
            ev.append({"t": s["t"], "kind": "invite", "name": nm,
                       "opening": bool(OPENING.search(ctx)), "ctx": ctx, "raw": txt})
            continue
        mt = THANKS.search(txt)
        if mt:
            v = re.search(r"谢谢|感谢", txt)
            nm = (best_name(txt[v.start():]) if v else None) or mt.group("name")
            if nm in NOT_A_NAME:
                continue                     # generic "感谢各位" -> NOT a boundary
            ev.append({"t": s["t"], "kind": "thanks", "name": nm, "raw": txt})
    return ev


def merge_invites(events, gap=30.0):
    """One hand-over can straddle two captions (measured: 0:15:21 + 0:15:30).

    Such a pair is ONE boundary: keep the earliest timestamp, carry over
    whichever part knew the name, and OR the 'opening' flag.
    """
    ev = sorted(events, key=lambda e: e["t"])
    out = []
    for e in ev:
        if (out and out[-1]["kind"] == "invite" and e["kind"] == "invite"
                and e["t"] - out[-1]["_last_t"] <= gap):
            prev = out[-1]
            prev["name"] = prev.get("name") or e.get("name")
            prev["opening"] = bool(prev.get("opening") or e.get("opening"))
            prev["ctx"] = (prev.get("ctx") or "") + " " + (e.get("ctx") or "")
            prev["raw"] = (prev.get("raw") or "") + " " + (e.get("raw") or "")
            prev["_last_t"] = e["t"]
            prev.setdefault("_merged_t", []).append(e["t"])
            continue
        e["_last_t"] = e["t"]
        out.append(e)
    return out


def dedupe(events, meta, norm):
    """Same hand-over twice -> keep the one whose slide text supports it."""
    buckets = {}
    for e in events:
        key = (e["kind"], norm(e.get("name") or ""), bool(e.get("opening")))
        buckets.setdefault(key, []).append(e)
    kept = []
    for key, group in buckets.items():
        if len(group) == 1:
            kept.append(group[0]); continue
        scored = []
        for e in group:
            n = page_at(meta, e["t"])
            notes = next((m.get("notes") or "" for m in meta if m["n"] == n), "") or ""
            hit = bool(e.get("name")) and e["name"] in notes
            scored.append((hit, e["t"], e))
        scored.sort(key=lambda x: (x[0], x[1]))       # prefer supported, then later
        best = scored[-1][2]
        best["dropped"] = [g["t"] for g in group if g is not best]
        kept.append(best)
    kept.sort(key=lambda e: e["t"])
    return kept


# ---------------------------------------------------------------- slide reading
# Tencent-Meeting burns "<name>的共享屏幕" into the frame. Inside a talk that
# name IS the presenter — the most reliable identity signal we have, stronger
# than ASR (which mis-hears) and stronger than a bare name badge.
PRESENTER_OVERLAY = re.compile(r"([" + CJK + r"]{2,4})\s*的共享屏幕")

# words that practically only appear in a talk title
TITLE_WORDS = re.compile(
    r"办法|条例|法规|政策|指导原则|指南|标准|规范|要点|解读|宣贯|贯彻|落实|构建|实践|"
    r"体系|合规|出海|管理|监测|警戒|评价|评估|风险|防线|进展|趋势|机遇|挑战|介绍|分享|汇报|报告|培训|"
    r"安全性|个例|上市后|全生命周期")


def clean_lines(text):
    """OCR lines minus recorder overlays / poster furniture / ASCII noise."""
    out = []
    for raw in (text or "").split("\n"):
        l = raw.strip()
        if not l or l in SHELL_LINES:
            continue
        if UI_NOISE.search(l):
            continue
        ascii_share = sum(c.isascii() for c in l) / max(len(l), 1)
        if ascii_share > 0.5:
            continue
        if DATE_ONLY.match(l):
            continue
        out.append(l)
    return out


def presenter_of(text):
    """Presenter name from the recorder overlay, or None."""
    m = PRESENTER_OVERLAY.search(text or "")
    if m:
        nm = m.group(1)
        if nm not in NOT_A_NAME and not ORG_MORPHEME.search(nm) and nm[0] in SURNAMES:
            return nm
    return None


def label_name(text):
    """Name printed after a 汇报人/主讲人 label, or None."""
    m = NAME_AFTER_LABEL.search(text or "")
    if m:
        nm = m.group(1)
        if nm not in NOT_A_NAME and not ORG_MORPHEME.search(nm):
            return nm
    return None


def bare_name(text):
    """A slide whose only content is a 2-4 char name (badge / cover style)."""
    bare = [l for l in clean_lines(text)
            if NAME_LINE.match(l) and l not in NOT_A_NAME
            and not ORG_MORPHEME.search(l) and l[0] in SURNAMES]
    return bare[-1] if bare else None


def slide_name(text):
    """Canonical speaker name printed on a slide, or None (overlay wins)."""
    return presenter_of(text) or label_name(text) or bare_name(text)


def title_line_of(text, speaker_name=None):
    """The talk title on a slide: a 《》 line first, else the longest clean line.

    Long titles wrap onto a second slide line and OCR reports the halves
    separately, so an adjacent qualifying line is re-joined:
      p4  贯彻落实《上海市药物警戒管理办法》 + 共同筑牢药品安全防线
      p94 创新药出海的药物警戒体系构建     + 与全球合规实践
    """
    lines = clean_lines(text)
    if not lines:
        return None

    def joiner(base):
        i = lines.index(base)
        if i + 1 >= len(lines):
            return base
        nxt = lines[i + 1]
        if (nxt != base and len(nxt) <= 16 and not DATE_ONLY.match(nxt)
                and not NAME_LINE.match(nxt)
                and not ORG_FOOTER.search(nxt)
                and not TITLE_PAGE_HINTS.search(nxt)):
            return base + nxt
        return base

    q = [l for l in lines if "《" in l or "》" in l]
    if q:
        return joiner(max(q, key=len))
    cand = [l for l in lines
            if len(l) >= 6 and not NAME_LINE.match(l)
            and not ORG_FOOTER.search(l)
            and not TITLE_PAGE_HINTS.search(l)]
    if speaker_name:
        cand = [l for l in cand if l.strip() != speaker_name]
    if not cand:
        return None
    best = max(cand, key=len)
    return joiner(best) if len(best) >= 8 else best


def score_page(text, speaker_name=None):
    """How likely is this slide the title page introducing `speaker_name`?"""
    if not text or not text.strip():
        return 0, None, None
    score = 0
    nm = slide_name(text)
    topic = title_line_of(text, speaker_name)
    ov = presenter_of(text)
    if ov:
        score += 5
        if speaker_name and (speaker_name in ov or ov in speaker_name):
            score += 3
    if TITLE_PAGE_HINTS.search(text):
        score += 2
    if speaker_name and nm and (speaker_name in nm or nm in speaker_name):
        score += 4
    elif nm:
        score += 1
    if topic:
        score += 1
        if len(topic) >= 10:
            score += 1
        if TITLE_WORDS.search(topic):
            score += 2
        if "《" in topic or "》" in topic:
            score += 3
    lines = clean_lines(text)
    if not lines:
        score -= 3
    if len(lines) <= 12:
        score += 1
    if re.search(r"\d{4}\s*[年.\-/]\s*\d{1,2}", text):
        score += 1
    return score, nm, topic


def find_name_in_window(meta, ocr, start_n, span, slide_count=None):
    """Best-supported speaker name in the opening window.

    Quality order matters more than distance: a recorder overlay beats a
    `汇报人：` label, which beats a bare name badge. A bare name is only trusted
    on a badge-like slide (few text lines) or one that also carries a title —
    otherwise ordinary content lines leak in as false names.
    """
    hi = min(start_n + span, slide_count) if slide_count else start_n + span
    window = [m["n"] for m in meta if start_n <= m["n"] <= hi]
    for fn in (presenter_of, label_name):
        for n in window:
            nm = fn(ocr.get(n, ""))
            if nm:
                return nm, n
    for n in window:
        txt = ocr.get(n, "")
        nm = bare_name(txt)
        if not nm:
            continue
        if len(clean_lines(txt)) > 6 and not title_line_of(txt, nm):
            continue
        return nm, n
    return None, None


def find_start(meta, ocr, start_n, asr_name=None, span=5, slide_count=None):
    """Locate the talk's opening slide and read who/what from it.

    It must be a FORWARD search: time→page mapping lands on the PREVIOUS slide
    because the host speaks before the speaker advances the deck
    (measured: 26→27, 93→94).
    """
    hi = min(start_n + span, slide_count) if slide_count else start_n + span
    best = {"page": None, "score": 0, "name": None, "topic": None, "name_page": None}
    for m in meta:
        n = m["n"]
        if n < start_n or n > hi:
            continue
        sc, nm, topic = score_page(ocr.get(n, ""), asr_name)
        if sc > best["score"]:
            best = {"page": n, "score": sc, "name": nm, "topic": topic, "name_page": None}
    nm, nm_page = find_name_in_window(meta, ocr, start_n, 4, slide_count)
    if nm:
        best["name"] = nm
        best["name_page"] = nm_page
        # the slide carrying the name is the talk's true first slide
        if best["page"] is None or abs(nm_page - start_n) <= 2:
            best["page"] = nm_page
            best["topic"] = title_line_of(ocr.get(nm_page, ""), nm)
    return best


def derive_name_fixes(sections, events, page_at_fn, meta):
    """ASR spelling -> slide spelling, for names heard slightly wrong.

    A fix is only published when the ASR name and the slide name have the SAME
    LENGTH, sit within 1-2 characters of each other, and agree on the first or
    the last character — measured cases: 史兰/史岚 (differ at 1 char, same head)
    and 蒲一虎/浦义虎 (differ at 2, same tail). That deliberately rejects the
    invitation verb glued onto a name (心徐建龙, 请蒲一虎): a parsing artefact of
    the transcript, not a spelling the reader would ever meet.
    """
    def near(a, b):
        if len(a) != len(b) or a == b or len(a) > 3:
            return False
        d = sum(1 for x, y in zip(a, b) if x != y)
        return 1 <= d <= 2 and (a[0] == b[0] or a[-1] == b[-1])

    fixes = {}
    for e in events:
        nm = e.get("name")
        if not nm:
            continue
        sec = None
        if e["kind"] == "invite":
            sec = next((s for s in sections if s.get("_from_t") == e["t"]), None)
        if sec is None:
            p = page_at_fn(meta, e["t"])
            sec = next((s for s in sections if s["from_n"] <= p <= s["to_n"]), None)
        if not sec:
            continue
        good = sec.get("_slide_name")
        if good and near(nm, good):
            fixes[nm] = good
    return fixes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--asr", required=True)
    ap.add_argument("--ocr", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", default=None)
    ap.add_argument("--deck-title", default="")
    ap.add_argument("--override", default=None,
                    help="JSON with a 'sections' list that replaces auto-detection")
    ap.add_argument("--fix-meta", action="store_true",
                    help="also rewrite slides_meta.json notes so every downstream "
                         "file spells the speaker names the way the slides do")
    args = ap.parse_args()

    meta = json.load(open(args.meta, encoding="utf-8"))
    meta.sort(key=lambda x: x["t"])
    last_n = max(m["n"] for m in meta)
    ocr = parse_ocr(args.ocr)

    def norm(s):
        return re.sub(r"\s+", "", s or "")

    log = []
    sections = []
    events = []

    if args.override:
        ov = json.load(open(args.override, encoding="utf-8"))
        raw = ov["sections"]
        log.append("## 使用 override（人工指定节定义）\n")
    else:
        segments = parse_asr(args.asr)
        log.append("## 自动检测\n- ASR 段数: %d\n" % len(segments))
        events = find_handovers(segments)
        log.append("- 候选串场句: %d 条\n" % len(events))
        for e in events:
            log.append("  - %s  %-7s %-6s 第%s页 | %s\n" % (
                fmt(e["t"]), e["kind"], e.get("name") or "?", page_at(meta, e["t"]), e["raw"][:60]))
        events = merge_invites(events)
        log.append("- 合并跨句串场后: %d 条\n" % len(events))
        events = dedupe(events, meta, norm)
        log.append("- 去重后边界事件: %d 条\n" % len(events))
        for e in events:
            if e.get("dropped"):
                log.append("  - 丢弃较早重复: %s\n" % [fmt(x) for x in e["dropped"]])
        raw = []
        for e in events:
            if e["kind"] != "invite":
                continue
            p0 = page_at(meta, e["t"])
            asr_name = e.get("name")
            st = find_start(meta, ocr, p0, asr_name, slide_count=last_n)
            entry = {
                "kind": "opening" if e.get("opening") else "talk",
                "speaker": st["name"] or asr_name,
                "from_n": st["page"] or p0,
                "_from_t": e["t"],
                "_asr_name": asr_name,
                "_slide_name": st["name"],
                "_slide_name_page": st.get("name_page"),
                "_title_page_score": st["score"],
                "_evidence": ["%s %s" % (fmt(e["t"]), e["raw"][:80])],
                # verbatim hand-over sentence: lets the HTML/PPT place the
                # divider at the exact paragraph mid-page instead of only
                # at a slide boundary
                "anchor": e["raw"],
                "anchor_t": e["t"],
            }
            if st["topic"]:
                entry["topic"] = st["topic"]
            if entry["kind"] == "opening" and not entry.get("topic"):
                entry["topic"] = "开班动员"
            raw.append(entry)

    # ---- fill in titles / topics / ranges ----
    for i, s in enumerate(raw, 1):
        s.setdefault("kind", "talk")
        s["idx"] = i
        n0 = s["from_n"]
        s.setdefault("start_para", 0)
        sp = s.get("speaker")
        if not s.get("topic"):
            s["topic"] = title_line_of(ocr.get(n0, ""), sp)
        if s.get("title"):
            pass
        elif s["kind"] == "opening":
            s["title"] = (sp or "未识别讲者") + "：" + (s.get("topic") or "开班动员")
        elif s["kind"] == "talk":
            tp = s.get("topic")
            s["title"] = (sp or "未识别讲者") + ("：《%s》" % tp.replace("《", "〈").replace("》", "〉") if tp else "")
        elif s["kind"] == "qa":
            s["title"] = "问答"
        elif s["kind"] == "panel":
            s["title"] = "专家点评"
        else:
            s["title"] = s.get("title") or "未命名"
        s["from_t"] = next((m["t"] for m in meta if m["n"] == n0), 0)
        sections.append(s)

    # contiguous ranges
    sections.sort(key=lambda s: s["from_n"])
    for i, s in enumerate(sections):
        nxt = sections[i + 1]["from_n"] if i + 1 < len(sections) else last_n + 1
        s["to_n"] = nxt - 1
        s["to_t"] = next((m["t"] for m in meta if m["n"] == nxt), 0) if nxt <= last_n else 0
    if sections:
        sections[0]["from_n"] = min(sections[0]["from_n"], 1)

    # Names must read the same in the deck, the viewer and the transcript. Where
    # the ASR heard something other than what the slide prints, publish the
    # correction so every downstream file can apply the same substitution.
    name_fixes = derive_name_fixes(sections, events, page_at, meta)
    if name_fixes:
        log.append("\n## 讲者姓名校正（ASR → 幻灯片）\n")
        for k, v in name_fixes.items():
            log.append("- %s → %s\n" % (k, v))

    out = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "deck_title": args.deck_title,
        "slide_count": last_n,
        "speakers": [s.get("speaker") for s in sections if s.get("speaker")],
        "name_fixes": name_fixes,
        "sections": sections,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log.append("\n## 最终节\n")
    for s in sections:
        log.append("- 节 %d: 页 %s–%s | %s | ASR姓名=%s 幻灯片姓名=%s(p%s)\n" % (
            s["idx"], s["from_n"], s["to_n"], s["title"],
            s.get("_asr_name"), s.get("_slide_name"), s.get("_slide_name_page")))
    if args.log:
        open(args.log, "w", encoding="utf-8").write("".join(log))

    print("sections: %d  ->  %s" % (len(sections), args.out))
    for s in sections:
        print("  [%d] p%s-%s  %s" % (s["idx"], s["from_n"], s["to_n"], s["title"]))
    print("  speakers:", " / ".join(out["speakers"]))
    if name_fixes:
        print("  name fixes:", "  ".join("%s→%s" % (k, v) for k, v in name_fixes.items()))

    if args.fix_meta and name_fixes:
        n_hit = 0
        for m in meta:
            txt = m.get("notes") or ""
            for k, v in name_fixes.items():
                if k in txt:
                    n_hit += txt.count(k)
                    txt = txt.replace(k, v)
            m["notes"] = txt
        json.dump(meta, open(args.meta, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("  slides_meta.json 姓名已校正 %d 处" % n_hit)


def fmt(t):
    return "%d:%02d:%02d" % (t // 3600, (t % 3600) // 60, t % 60)


if __name__ == "__main__":
    main()
