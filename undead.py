import sys
import signal
import time

def ignore(signum, frame):
    pass

signal.signal(signal.SIGINT, ignore)
signal.signal(signal.SIGTERM, ignore)

while True:
    print(time.time())
    time.sleep(1)

