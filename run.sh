#/bash/sh
cd /home/pi/under-one-sky
python3 -m underonesky.supervisor --ledplay_startup 2 --kill_existing --ip 192.168.0.143 --port 9999 --ledplay_ip 192.168.0.143 --ledplay_port 1234
