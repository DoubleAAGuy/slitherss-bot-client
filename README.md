# slither.io Bot Client

Connects to any slither.io-protocol server and spawns configurable bots that steer toward the center of the map.

## Quick Setup

```bash
# Remove old copy (if any)
rm -rf slitherss-bot-client                 # Linux/macOS
Remove-Item -Recurse -Force slitherss-bot-client  # Windows PowerShell

git clone https://github.com/DoubleAAGuy/slitherss-bot-client
cd slitherss-bot-client
pip install websockets
python bot.py
```

Enter the server IP, port, and number of bots when prompted.

### Example

```
Server IP (default 127.0.0.1): 192.211.52.146
Server port (default 444): 444
Path (default /slither): /slither
Number of bots: 20
```
