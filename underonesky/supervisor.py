"""
    Copyright (C) 2021 Mauricio Bustos (m@bustos.org)
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import argparse
import asyncio
import time
import json
import logging
import subprocess
from logging.handlers import RotatingFileHandler

from underonesky.display_animations import State
from underonesky.earth_data.earth_data import moon_phase, lights_out, current_sunset, PHASE_NAME

try:
    from gpiozero import DigitalOutputDevice, DigitalInputDevice
except ImportError:
    from gpiozero_sim import DigitalOutputDevice, DigitalInputDevice
from pythonosc import osc_message_builder
from pythonosc import udp_client
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from yoctopuce.yocto_watchdog import *
from yoctopuce.yocto_temperature import *

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('supervisor')
logger.setLevel(logging.INFO)
log_format = logging.Formatter(FORMAT)

file_handler = RotatingFileHandler('underonesky_supervisor.log', maxBytes=20000, backupCount=5)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

supervision = None
led_play = None
watchdog = None
temp_sensor = None
power_pin = None
phase_pin_numbers = [8, 9, 10, 11, 12, 13, 14, 15]
phase_pins = []

last_external = None


def handle_test(unused_addr=None, index=None):
    logger.info('Run a test cycle')
    if watchdog:
        watchdog.resetWatchdog()
    handle_power_on()
    for phase in range(2, 9):
        logger.info("Phase " + PHASE_NAME[phase])
        handle_phase_select(phase)
        time.sleep(1)
    handle_phase_select(0)
    handle_power_off()
    time.sleep(5)


def handle_power_on(unused_addr=None, index=None):
    logger.info('Power on')
    power_pin.on()


def handle_power_off(unused_addr=None, index=None):
    logger.info('Power off')
    power_pin.off()


def handle_phase_select(index=None):
    """Handle the moon phase select"""
    map(lambda x: x.off(), phase_pins)
    if index > 1:
        phase_pins[index - 1].on()


async def main_loop(ledplay_startup, disable_sun, upper_temp):
    """ Main execution loop """
    global last_external

    current_moon_phase = 0
    current_state = State.STOPPED
    handle_power_off()

    """ Wait prescribed time for LED play to start up """
    await asyncio.sleep(ledplay_startup)

    while True:
        """ Health checks """
        if watchdog:
            watchdog.resetWatchdog()
        if last_external is not None:
            if (datetime.datetime.now() - last_external).seconds > 60:
                last_external = None
            await asyncio.sleep(1)
            continue
        current_temperature = YTemperature.FirstTemperature().get_currentValue()
        if current_temperature > upper_temp:
            if current_state != State.STOPPED:
                logger.warning('Shutting down due to over temp {}'.format(current_temperature))
                current_state = State.STOPPED
                handle_power_off()
            handle_phase_select(0)
            await asyncio.sleep(1)
            continue
        """ Check on/off timing"""
        if disable_sun:
            main_led_off = False
            moon_off = False
        else:
            main_led_off = lights_out(supervision['lights_on'], supervision['lights_off'])
            moon_off = lights_out(supervision['lights_on'])
        if main_led_off:
            if current_state != State.STOPPED:
                handle_power_off()
                current_state = State.STOPPED
            elif power_pin.value:
                handle_power_off()
        else:
            if current_state == State.STOPPED:
                handle_power_on()
                current_state = State.RUNNING
        if moon_off:
            handle_phase_select(0)
            current_moon_phase = 0
            logger.info('Shutting down moon')
        else:
            level = int(moon_phase())
            if current_moon_phase != level:
                handle_phase_select(level)
                current_moon_phase = level
                logger.info('Moving to moon phase {}'.format(PHASE_NAME[level]))

        await asyncio.sleep(1)


async def init_main(args, dispatcher, sensor_dispatcher):
    """ Initialization routine """
    loop = asyncio.get_event_loop()
    server = AsyncIOOSCUDPServer((args.ip, args.port), dispatcher, loop)
    transport, _ = await server.create_serve_endpoint()

    sensor_server = AsyncIOOSCUDPServer((args.controller_ip, args.controller_port), sensor_dispatcher, loop)
    server_transport, _ = await sensor_server.create_serve_endpoint()

    await main_loop(args.ledplay_startup, args.disable_sun, args.temperature_shutoff_c)

    transport.close()


if __name__ == "__main__":

    os.system('hwclock -s')

    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', default='192.168.4.1', help='The ip to listen on')
    parser.add_argument('--port', type=int, default=9999, help='The port to listen on')
    parser.add_argument('--controller_ip', default='192.168.4.1', help='The controller ip address')
    parser.add_argument('--controller_port', type=int, default=9998, help='The port that the controller is listening on')
    parser.add_argument('--ledplay_ip', default='192.168.4.1', help='The LED Play ip address')
    parser.add_argument('--ledplay_port', type=int, default=1234, help='The port that the LED Play application is listening on')
    parser.add_argument('--ledplay_startup', required=False, type=int, default=60, help='Time to wait before LEDPlay starts up')
    parser.add_argument('--config', required=False, type=str, default='underonesky/supervision.json')
    parser.add_argument('--disable_sun', dest='disable_sun', action='store_true')
    parser.add_argument('--temperature_shutoff_c', required=False, type=int, default=28, help='Upper temp (in C) to shutdown system')
    parser.add_argument('--kill_existing', dest='kill_existing', action='store_true')
    parser.add_argument('--test_phases', dest='test_phases', action='store_true')
    parser.set_defaults(disable_sun=False, kill_existing=False)
    args = parser.parse_args()

    if args.kill_existing:
        subprocess = subprocess.Popen(['ps', '-A'], stdout=subprocess.PIPE)
        output, error = subprocess.communicate()
        this_pid = os.getpid()
        target_process = "python"
        for line in output.splitlines():
            if target_process in str(line):
                pid = int(line.split(None, 1)[0])
                if pid != this_pid:
                    logger.warning('Killing existing python processes')
                    os.kill(pid, 9)

    with open(args.config, 'r') as file:
        supervision = json.load(file)
        power_pin = DigitalOutputDevice(supervision['power_pin'])
    for pin in phase_pin_numbers:
        phase_pins.append(DigitalOutputDevice(pin))

    errmsg = YRefParam()
    if YAPI.RegisterHub('usb', errmsg) != YAPI.SUCCESS:
        logger.error('YAPI init error ' + errmsg.value)
    else:
        temp_sensor = YTemperature.FirstTemperature()
        if temp_sensor:
            temp_sensor_name = temp_sensor.get_module().get_serialNumber() + '.temperature'
        else:
            logger.error('No temp sensor connected')
        watchdog = YWatchdog.FirstWatchdog()
        if watchdog:
            watchdog.resetWatchdog()
        else:
            logger.error('No watchdog connected')

    led_play = udp_client.UDPClient(args.ledplay_ip, args.ledplay_port)

    dispatcher = Dispatcher()
    dispatcher.map('/poweron', handle_power_on)
    dispatcher.map('/poweroff', handle_power_off)
    dispatcher.map('/test', handle_test)

    sensor_dispatcher = Dispatcher()

    logger.info('Serving on {}:{}'.format(args.ip, args.port))
    logger.info('Current moon phase is {}'.format(PHASE_NAME[moon_phase()]))
    logger.info('Current sunset is {} UTC'.format(current_sunset()))

    if args.test_phases:
        while True:
            handle_test()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_main(args, dispatcher, sensor_dispatcher))
