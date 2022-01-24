import time
from yoctopuce.yocto_watchdog import *

errmsg = YRefParam()

if YAPI.RegisterHub('usb', errmsg) != YAPI.SUCCESS:
   print('YAPI init error ' + errmsg.value)
else:
   watchdog = YWatchdog.FirstWatchdog()
   while True:
      watchdog.set_running(YWatchdog.RUNNING_OFF)
      time.sleep(10)
      print("OFF")
