#!/bin/bash
cd /home/pi/under-one-sky
source venv/bin/activate
python3 -m underonesky.supervisor --ledplay_startup 2 --kill_existing --ip 192.168.86.250 --port 9999 --ledplay_ip 192.168.86.250 --ledplay_port 1234
#python3 -m underonesky.supervisor --ledplay_startup 2 --kill_existing --ip 192.168.0.143 --port 9999 --ledplay_ip 192.168.0.143 --ledplay_port 1234
