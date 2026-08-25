# CICFlowMeter (Java, v4.0) — WSL Setup Guide

This is the exact, working path to get CICFlowMeter compiled and running on WSL
(Ubuntu), distilled from a real from-scratch install. Follow it in order — don't
skip ahead. Every step here exists because a shortcut broke last time.

Do this once per teammate, on their own machine. Budget ~45–60 minutes if nothing
goes wrong, longer if you hit a Java-version mismatch (very common — see Step 4).

---

## 0) Before you start

Know your Windows username (`whoami` in PowerShell, or just look at your `C:\Users\`
folder). You'll need it for paths. If your username has a space or capital letters
that don't match what you expect, that alone can waste an hour — check it now.

---

## 1) Install the WSL prerequisites

```bash
sudo apt update
sudo apt install -y openjdk-8-jdk libpcap-dev maven gradle
```

- **openjdk-8-jdk** — CICFlowMeter's build system (old Gradle) cannot compile
  under Java 11+. You need Java 8 specifically, installed *alongside* whatever
  version WSL already shipped with — don't uninstall the newer one, we'll switch
  between them in Step 4.
- **libpcap-dev** — the library that lets Linux actually read raw packets.
- **maven / gradle** — build tools.

---

## 2) Clone the CICFlowMeter source

```bash
cd ~
git clone https://github.com/ISCX/CICFlowMeter.git
cd CICFlowMeter
```

Verify the native library files exist before doing anything else:
```bash
ls jnetpcap/linux/jnetpcap-1.4.r1425
```
You should see `jnetpcap.jar` and `libjnetpcap.so`. If this folder is empty or
missing, the clone didn't pull everything — don't proceed until these two files
are there.

---

## 3) Register jnetpcap with Maven

jnetpcap isn't on public Maven repos, so you install it locally, from inside the
CICFlowMeter folder:

```bash
mvn install:install-file \
  -Dfile=jnetpcap/linux/jnetpcap-1.4.r1425/jnetpcap.jar \
  -DgroupId=org.jnetpcap \
  -DartifactId=jnetpcap \
  -Dversion=1.4.1 \
  -Dpackaging=jar
```

This should print `BUILD SUCCESS`. If it doesn't, stop here — nothing past this
point will work.

---

## 4) Switch to Java 8 for the build (the step that eats the most time)

Go back to the project root and try building:
```bash
cd ~/CICFlowMeter
chmod +x gradlew
./gradlew build
```

**If you see:**
```
Could not determine java version from '11.0.x'.
```
Gradle is using the wrong Java. Fix it:
```bash
sudo update-alternatives --config java
sudo update-alternatives --config javac
```
Each command shows a numbered list — pick the one pointing at
`java-8-openjdk`/`jre-8` for **both** commands (not just `java`). Confirm:
```bash
java -version
```
Must print `1.8.0_...`. If it still shows 11 or higher, the `update-alternatives`
selection didn't take — redo it.

Then rebuild:
```bash
./gradlew clean build
```

**If the build fails on Checkstyle or Test errors** (common, and safe to ignore
for our purposes — we only need the JARs, not a clean lint pass):
```bash
./gradlew assemble
```

**Success looks like:** `BUILD SUCCESSFUL in Xs`.

---

## 5) Package it into a runnable distribution

```bash
./gradlew distZip
cd build/distributions
```

**Extract with `jar`, not `unzip`.** `unzip` on newer Ubuntu throws a false
"invalid zip file with overlapped components (possible zip bomb)" error on this
specific archive. Use:
```bash
jar -xvf CICFlowMeter-4.0.zip
```

Then:
```bash
cd CICFlowMeter-4.0/bin
chmod +x cfm
```

Quick sanity check (don't expect a help menu — this tool doesn't have one; an
error about a missing pcap file actually means it loaded correctly):
```bash
./cfm -h
```
If you see `The pcap file or folder does not exist! -> -h`, that's fine — it
means the Java engine and native libraries linked successfully.

---

## 6) Run a real conversion

```bash
sudo ./cfm "/path/to/input.pcap" "/path/to/output_folder/"
```

Notes:
- **Always use `sudo`** — the tool needs root to touch the packet libraries,
  even for reading an existing file offline.
- **Always use absolute paths**, not relative ones (`./file.pcap` can confuse it).
- **Always end the output path with a trailing `/`** — without it the tool can
  misread the folder as a filename and fail.
- If your input file is on your Windows drive, WSL sees it at
  `/mnt/c/Users/<YourWindowsUsername>/...` or `/mnt/d/...` — confirm your exact
  username first with `ls /mnt/c/Users/`, don't assume it matches your WSL
  username.

You'll see a wall of `Forward flow closed due to FIN Flag` lines while it runs —
that's normal, it's just logging each completed conversation. Wait for the
terminal to return to a prompt and print a final summary line
(`... is done. total N flows ...`) before touching the output file.

---

## 7) "Come back tomorrow" — the short version

Once steps 1–5 are done once, you never repeat them. Every future session is
just:
```bash
cd ~/CICFlowMeter/build/distributions/CICFlowMeter-4.0/bin
sudo ./cfm "/path/to/input.pcap" "/path/to/output/"
```

Optional shortcut — add an alias once:
```bash
echo "alias gocic='cd ~/CICFlowMeter/build/distributions/CICFlowMeter-4.0/bin'" >> ~/.bashrc
source ~/.bashrc
```
Then just type `gocic` to jump straight there.

---

## Known gotchas (things that cost real time last round)

1. **C: drive space.** WSL's entire filesystem lives inside a `.vhdx` file on
   `C:` by default, and it never auto-shrinks. If `C:` is tight, do your actual
   pcap/CSV work under `/mnt/d/...` instead of your Linux home directory — keeps
   large files off `C:` entirely. You don't need to move WSL itself for this
   project; just point inputs/outputs at `/mnt/d/...`.

2. **Don't split large pcaps by packet count before running CICFlowMeter.**
   Splitting mid-conversation cuts flows in half (SYN in one file, FIN in the
   next), and the tool silently discards anything it can't reconstruct as a
   complete conversation — you can lose the vast majority of expected flows this
   way. If a file is too large to handle in one piece, let CICFlowMeter process
   the whole thing (or a whole folder) rather than pre-splitting it. If you're
   stuck with parts (e.g. split with `editcap`), merge them back first:
   ```bash
   sudo apt install -y tshark   # provides mergecap
   mergecap -w restored.pcap part_*.pcap
   ```

3. **Path/username mismatches are the #1 silent failure.** "File does not
   exist" errors were repeatedly caused by assuming a Windows username instead
   of checking it. Always run `ls /mnt/c/Users/` (or `/mnt/d/...`) once per
   machine to confirm the real path before trusting a command someone else
   wrote.

4. **This guide only covers converting a pcap you already have into a CSV.**
   Live two-machine attacker/victim capture (getting both systems on the same
   subnet, firewall rules, which interface to `tcpdump`/`tshark` on) is a
   separate, much longer troubleshooting path — that's covered in the victim-
   dashboard README, not here.