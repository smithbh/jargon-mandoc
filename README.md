
# jargon-mandoc

Generate a Unix man page from the **Jargon File** so you can read it with
`man jargon`.

The script parses the Jargon File as distributed in GNU Info (Texinfo `.info`)
form — e.g. `jarg400.info` — and emits a single classic `man(7)`-macro page
covering the front matter, all ~2,000 lexicon entries, and the appendices.

-----

## Acknowledgements
This script uses the debian-maintained jargon file, hosted at:
https://salsa.debian.org/debian/jargon/-/tree/2420aed100bf9afb10c0f7eee965f64834dda003/

## Requirements

|Component                |Needed for                                           |
|-------------------------|-----------------------------------------------------|
|Python ≥ 3.8             |running the script (standard library only, no deps)  |
|`jarg400.info`           |input — the 4.x Jargon File in Texinfo `.info` format|
|`groff` / `mandoc`       |rendering the page (`man` already pulls one in)      |
|`mandb` *or* `makewhatis`|building the `whatis`/`apropos` index (optional)     |

The script itself imports only the Python standard library.

-----

## Quick start

```sh
# render + install into a user-owned man directory
python3 jargon-mandoc.py jarg400.info --install
man jargon
```

`--install` writes to `~/.local/share/man/man7/jargon.7`. If `man jargon`
doesn’t find it, that directory isn’t on your man search path — see
[Making `man jargon` resolve](#making-man-jargon-resolve) below.

-----

## Usage

```
python3 jargon-mandoc.py INPUT [INPUT ...] [options]
```

|Option                  |Effect                                                      |
|------------------------|------------------------------------------------------------|
|`INPUT`                 |one or more `jarg*.info` files (concatenated into one page) |
|`-o`, `--output-dir DIR`|directory to write `jargon.7` into (default: `./jargon-man`)|
|`--gzip`                |also emit `jargon.7.gz`                                     |
|`--install`             |copy the page into `~/.local/share/man/man7`                |
|`--install-dir DIR`     |copy the page into `DIR` instead (implies install)          |

All path arguments accept `~` and `$VAR`; they are expanded by the script even
when the shell leaves them literal (see [Gotchas](#gotchas)).

### Examples

```sh
# just generate the page, inspect it, install nothing
python3 jargon-mandoc.py jarg400.info -o ./build
groff -man -Tutf8 ./build/jargon.7 | less -R

# generate a compressed copy as well
python3 jargon-mandoc.py jarg400.info -o ./build --gzip

# install system-wide (needs write access / sudo)
sudo python3 jargon-mandoc.py jarg400.info --install-dir /usr/local/share/man/man7
```

-----

## Making `man jargon` resolve

A man page is found only if the directory **above** its `manN/` subdirectory is
on the man search path. Pick the workflow matching your `man` implementation.

### GNU/Linux (`man-db`)

```sh
python3 jargon-mandoc.py jarg400.info --install
mandb ~/.local/share/man            # index the directory you own
export MANPATH="$HOME/.local/share/man:$(manpath)"   # add to ~/.profile etc.
man jargon
```

### BSD / Alpine / OpenBSD (`mandoc`)

`mandocdb` was renamed to `makewhatis`; use whichever your system ships.

```sh
python3 jargon-mandoc.py jarg400.info --install
makewhatis ~/.local/share/man       # writes ~/.local/share/man/mandoc.db
export MANPATH="$HOME/.local/share/man:"             # trailing ':' = append defaults
man jargon
```

### No persistent configuration

Override the search path for a single invocation — no `MANPATH`, no database:

```sh
man -M ~/.local/share/man jargon
```

`mandoc`’s `man` does a filesystem fallback search, so this works even before
you build an index. `groff`/`man-db` likewise accept `-M`.

### Render the file directly

```sh
man -l ./build/jargon.7      # man-db and recent mandoc
mandoc ./build/jargon.7      # mandoc, always
```

Verify resolution and indexing:

```sh
man -w jargon        # prints the resolved path
whatis jargon        # NAME line, from the database
apropos hacker       # full-text search, from the database
```

-----

## How it works

The Info file stores the document as a flat list of *nodes* separated by the
byte `0x1f`, each opening with a `File:/Node:/Next:/Prev:/Up:` header. Lexicon
entries are the nodes whose `Up:` field is a letter bucket (`= A =`, `= B =`,
…) and whose body begins with a `:term:` marker. The script keys off that
structure rather than guessing from prose.

- Headwords are set in **bold**; `{cross-references}` are set in *italic* with
  their braces kept, so in-pager searches like `/{foo}` still work.
- Lexicon bodies are rendered **verbatim** (`.nf`/`.fi`, no-fill). The Jargon
  File is hand-wrapped at ~70 columns and full of ASCII art, aligned tables,
  and quoted code; reflowing would destroy that layout. The tradeoff is that
  art lines do not adapt to terminals narrower than 80 columns.

-----

## Gotchas

- **Literal `~` in `--install-dir=...`** — the shell performs tilde expansion
  only when `~` is word-initial. `--install-dir=~/man` leaves the `~` literal;
  `--install-dir ~/man` (space) does not. The script expands either form, but
  if you ran an older copy and ended up with a directory literally named `~`,
  remove it with `rm -ri ./~` (the `./` prevents the shell from expanding it
  to your home directory).
- **`MANPATH` semantics differ slightly.** With `mandoc`, an empty element
  (leading/trailing colon) is replaced by the compiled-in default path, so
  `"$HOME/.local/share/man:"` means “mine first, then the defaults.” `man-db`
  honors the same convention; `$(manpath)` spells the defaults explicitly.
- **`man-db` does not auto-search `~/.local/share/man`** unless that root is
  derivable from your `PATH` or already in `manpath`. Set `MANPATH` or install
  into a system man root.
- **`--gzip` plus a plain copy in the same directory** yields a duplicate
  `apropos`/`whatis` hit, since the indexer reads both `jargon.7` and
  `jargon.7.gz`. Keep only one.
- **Input format.** The script targets the **4.x Texinfo `.info`** build. The
  older 2.x/3.x flat-text releases (`jargXXX.txt`) have no node structure and
  will not parse — the script reports `no Info nodes found`.

-----

## License

The Jargon File is in the public domain. This script is provided as-is; treat
it as public domain as well.
