"""Conservative cleanup for timestamped ASR text.

Keeps every timestamp and only performs exact user-supplied replacements plus
collapse of immediately repeated long phrases, a common Whisper failure mode.
"""
import argparse
import json
import re


TS_LINE = re.compile(r"^(\[[^]]+\]\s*)(.*)$")


def collapse_repeated_phrases(text):
    """Collapse adjacent exact repetitions of phrases eight+ characters long."""
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(.{8,80}?)(?:\1){1,}", r"\1", text)
    return text


def normalize_punctuation(text):
    """Normalize repeated/contradictory punctuation without rewriting words."""
    text = re.sub(r"([，。！？；：、])\1+", r"\1", text)
    text = re.sub(r"。[,，]", "。", text)
    text = re.sub(r"[,，]([。！？；])", r"\1", text)
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--replacements-json", default=None,
                        help="JSON object mapping recognized text to corrections")
    args = parser.parse_args()

    replacements = {}
    if args.replacements_json:
        with open(args.replacements_json, encoding="utf-8") as handle:
            replacements = json.load(handle)
        if not isinstance(replacements, dict):
            raise ValueError("replacements JSON must be an object")

    output = []
    with open(args.input, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            match = TS_LINE.match(line)
            prefix, text = (match.group(1), match.group(2)) if match else ("", line)
            text = collapse_repeated_phrases(text)
            text = normalize_punctuation(text)
            for source, target in replacements.items():
                text = text.replace(source, target)
            output.append(prefix + text.strip())

    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(output) + "\n")
    print("cleaned %d lines -> %s" % (len(output), args.output))


if __name__ == "__main__":
    main()
