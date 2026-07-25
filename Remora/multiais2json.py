'''Go to
https://www.marinetraffic.com/en/ais/details/ships/shipid:5261520
(That's the Rome Trader) Copy the data block beginning with
"Navigational status..." down to "Reported ETA..."  Paste it at the
top of <multiais file we're using -- on my machine it's
~/Downloads/rometrader.multiais). Then run this and give that file as
the input. It'll send to stdout the contents of the above file,
converted to a JSON array. (Don't worry about where you put these, or
adding complex separators. Just make sure there's a newline separator
at least. There's enough info to decode what was where when in the
data.)

'''

import sys
import json

def clean_value(v):
    v = v.strip()

    # numeric with units
    if v.endswith(" kn"):
        try: return float(v[:-3])
        except: return v

    if v.endswith(" m"):
        try: return float(v[:-2])
        except: return v

    if v.endswith(" °"):
        try: return int(v[:-2])
        except: return v

    return v


def parse_blocks(path):
    blocks = []
    current = None

    with open(path, "r", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            # must contain a tab separator
            if "\t" not in line:
                continue

            key, value = line.split("\t", 1)
            key = key.strip()
            value = clean_value(value)

            # NEW BLOCK begins when we see "Navigational status"
            if key == "Navigational status":
                # if an old block exists, save it
                if current:
                    blocks.append(current)
                # start new block
                current = {}

            # only store fields if we are inside a block
            if current is not None:
                current[key] = value

    # Append last block if any
    if current:
        blocks.append(current)

    return blocks


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_ais_blocks.py <inputfile>")
        sys.exit(1)

    infile = sys.argv[1]
    blocks = parse_blocks(infile)

    print(json.dumps(blocks, indent=2))


if __name__ == "__main__":
    main()
