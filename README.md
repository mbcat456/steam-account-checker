# Steam account checker

Multithreaded python steam account checker. It validates accounts through Steam's public API, then pulls full profile stats including wallet balance, game library, country, and VAC ban status.

### Features
- multithreaded login checking with live progress bar and valid printing
- automatic proxy rotation for sticky proxies
- session resume (stop and continue later without losing progress)
- pulls wallet balance, full game list, country, and VAC ban status for valid accounts
- any proxy format supported

### Prerequisites
Python 3.10 or higher.

### Installation

1. Clone the repository or download the files.
2. Open a terminal in the folder and install the required python packages:

```bash
pip install -r requirements.txt
```

### Setup

Before running the checker, you need to set up your proxies and combo list.

Proxies:
create a file named `proxies.txt` in the same directory as the script. paste your proxies inside, one per line. if `proxies.txt` is missing, the script will ask you to point at another proxy file — it won't run without one. the parser auto-detects any standard format:
- `ip:port`
- `ip:port:user:pass`
- `user:pass@ip:port`
- `http://user:pass@ip:port`

Accounts:
have a combo file ready with your accounts formatted as `username:password` per line. the file can have any name — you'll type it at the prompt.

### Usage

Run the script from your terminal:

```bash
python v5_rewrite.py
```

The script will prompt you for a few things:
1. Combo file: type the name of your combo file (e.g., `combo.txt` or just `combo`) and press enter.
2. Threads: how many concurrent checks to run. default is 150.
3. Retries: max retries per account for transient errors like connection drops or empty responses. type `0` for unlimited.

If a previous session is found for the same combo file, it asks whether to resume from where you left off.

Once it starts, it cycles through your proxies automatically. the bar at the bottom tracks progress in real time. valid hits print above the bar as they're found.

### Output files
- `hits.txt` — valid accounts with full profile data
- `custom.txt` — accounts with 2FA enabled
- `unresolved.txt` — accounts that couldn't be resolved after max retries
- `session_state.json` — progress saved every 5 seconds for resume

### Output format
When an account hits, it saves to `hits.txt` like this:

    username:password | Wallet Balance = >$12.34 USD | Games owned = Counter-Strike 2, Rust, VRChat | Country = United States | VAC ban = false | SteamID = 76561191234567890

### Notes
- If you're getting tons of retries/errors, your proxies are either dead or getting rate limited. rotating residential/datacenter proxies work best.
- unlimited retries can hang an account forever if steam returns something the code doesnt handle
- Ctrl+C saves progress before exiting. you can resume later.
