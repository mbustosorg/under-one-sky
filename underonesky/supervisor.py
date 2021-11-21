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
import os
import subprocess
from logging.handlers import RotatingFileHandler

from underonesky.display_animations import State
from underonesky.earth_data.earth_data import moon_phase, lights_out, current_sunset, current_sunrise, PHASE_NAME

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
temp_sensor_1 = None
temp_sensor_2 = None
max_cpu_temp = 60
max_led_temp = 60
temp_shutdown = {
    "cpu": 0,
    "temp_1": 0,
    "temp_2": 0
}
last_temp = {
    "cpu": 0,
    "temp_1": 0,
    "temp_2": 0
}
power_pin = None
phase_pin_numbers = [25, 24, 13, 12, 11, 10, 9, 8]
phase_pins = []
current_moon_phase = 0

last_external = None

BACKGROUND_RUN_INDEX = "/LEDPlay/player/backgroundRunIndex"
BACKGROUND_MODE = '/LEDPlay/player/backgroundMode'


def pi_temp() -> float:
    """Onboard CPU temperature"""
    temp = os.popen("cat /sys/class/thermal/thermal_zone0/temp").read()
    return float(int(float(temp) / 1000.0))


def handle_test(unused_addr=None, index=None) -> None:
    """Set a phase"""
    global current_moon_phase

    if 1 <= index <= 8:
        current_moon_phase = index
        logger.info("Test phase " + PHASE_NAME[current_moon_phase])
        handle_phase_select(current_moon_phase)
        time.sleep(10)


def handle_cpu_temp(unused_addr=None, index=None) -> None:
    """Override the CPU temp"""
    global last_temp
    global last_external

    logger.info('Override CPU Temp to {}'.format(index))
    last_temp['cpu'] = index
    last_external = datetime.datetime.now()


def handle_led_temp(unused_addr=None, index=None) -> None:
    """Override the LED temp"""
    global last_temp
    global last_external

    logger.info('Override LED Temps to {}'.format(index))
    last_temp['temp_1'] = index
    last_external = datetime.datetime.now()


def handle_full_test(unused_addr=None, index=None) -> None:
    """Run a test cycle"""
    global current_moon_phase

    for i in range(2):
        logger.info('Run a test cycle')
        logger.info('CPU temp (c) = {}'.format(pi_temp()))
        if watchdog:
            watchdog.resetWatchdog()
        current_temperature_1 = temp_sensor_1.get_currentValue()
        current_temperature_2 = temp_sensor_2.get_currentValue()
        logger.info('Thermocouple 1 (c) = {}'.format(current_temperature_1))
        logger.info('Thermocouple 2 (c) = {}'.format(current_temperature_2))
        for phase in range(1, 9):
            logger.info("Phase {} [{}]".format(PHASE_NAME[phase], phase))
            handle_phase_select(phase)
            time.sleep(2)
        handle_phase_select(0)
        time.sleep(5)
    current_moon_phase = 0


def handle_background_mode(unused_addr, index):
    """ Process the BACKGROUND_MODE message """
    logger.info('{} {}'.format(BACKGROUND_MODE, index))
    msg = osc_message_builder.OscMessageBuilder(address=BACKGROUND_MODE)
    msg.add_arg(index)
    led_play.send(msg.build())


def handle_background_run_index(unused_addr, index, external=True):
    """ Process the BACKGROUND_RUN_INDEX message """
    global last_external

    if not power_pin.value:
        handle_power_on()
    logger.info('{} {}'.format(BACKGROUND_RUN_INDEX, index))
    msg = osc_message_builder.OscMessageBuilder(address=BACKGROUND_RUN_INDEX)
    msg.add_arg(index)
    led_play.send(msg.build())
    if external:
        last_external = datetime.datetime.now()


def handle_power_on(unused_addr=None, index=None):
    logger.info('Main LED power on')
    power_pin.on()


def handle_power_off(unused_addr=None, index=None):
    logger.info('Main LED power off')
    power_pin.off()


def handle_phase_select(index=None):
    """Handle the moon phase select"""
    list(map(lambda x: x.off(), phase_pins))
    if 2 <= index <= 8:
        logger.info('Moved to moon phase {} [{}]'.format(PHASE_NAME[index], index))
        phase_pins[index - 2].on()


async def main_loop(ledplay_startup, disable_sun, debug):
    """ Main execution loop """
    global last_external
    global current_moon_phase
    global temp_shutdown

    current_state = State.STOPPED
    handle_power_off()

    """ Wait prescribed time for LED play to start up """
    await asyncio.sleep(ledplay_startup)

    while True:
        """ Health checks """
        if watchdog and not debug:
            watchdog.resetWatchdog()
        if last_external is not None:
            if (datetime.datetime.now() - last_external).seconds > 10:
                last_external = None
        else:
            last_temp['cpu'] = pi_temp()
            last_temp['temp_1'] = temp_sensor_1.get_currentValue() if temp_sensor_1 else 0
            last_temp['temp_2'] = temp_sensor_2.get_currentValue() if temp_sensor_2 else 0
        if temp_shutdown['cpu'] or temp_shutdown['temp_1'] or temp_shutdown['temp_2']:
            if temp_shutdown['cpu']:
                if max_cpu_temp - supervision['cpu_temp_hysteresis'] > last_temp['cpu']:
                    temp_shutdown['cpu'] = 0
                    logger.warning('CPU cooled down to {}'.format(last_temp['cpu']))
            if temp_shutdown['temp_1']:
                if max_led_temp - supervision['led_temp_hysteresis'] > last_temp['temp_1']:
                    temp_shutdown['temp_1'] = 0
                    logger.warning('LED temp 1 cooled down to {}'.format(last_temp['temp_1']))
            if temp_shutdown['temp_2']:
                if max_led_temp - supervision['led_temp_hysteresis'] > last_temp['temp_2']:
                    temp_shutdown['temp_2'] = 0
                    logger.warning('LED temp 2 cooled down to {}'.format(last_temp['temp_1']))
            await asyncio.sleep(1)
            continue
        if last_temp['cpu'] > max_cpu_temp:
            if current_state != State.STOPPED:
                logger.warning('Shutting down due to CPU over temp {}'.format(last_temp['cpu']))
                current_state = State.STOPPED
                shutdown_led_sequence()
            temp_shutdown['cpu'] = last_temp['cpu']
            handle_phase_select(0)
            current_moon_phase = 0
            await asyncio.sleep(1)
            continue
        if last_temp['temp_1'] > max_led_temp:
            if current_state != State.STOPPED:
                logger.warning('Shutting down due to over temp {}'.format(last_temp['temp_1']))
                current_state = State.STOPPED
                shutdown_led_sequence()
            temp_shutdown['temp_1'] = last_temp['temp_1']
            handle_phase_select(0)
            current_moon_phase = 0
            await asyncio.sleep(1)
            continue
        if last_temp['temp_2'] > max_led_temp:
            if current_state != State.STOPPED:
                logger.warning('Shutting down due to over temp {}'.format(last_temp['temp_2']))
                current_state = State.STOPPED
                shutdown_led_sequence()
            temp_shutdown['temp_2'] = last_temp['temp_2']
            handle_phase_select(0)
            current_moon_phase = 0
            await asyncio.sleep(1)
            continue
        """ Check on/off timing"""
        if disable_sun:
            main_led_off = False
            moon_off = False
        else:
            main_led_off = lights_out(supervision['leds_on'], supervision['leds_off'])
            moon_off = lights_out(supervision['moons_on'])
        if main_led_off:
            if current_state != State.STOPPED:
                current_state = State.STOPPED
                shutdown_led_sequence()
            elif power_pin.value:
                shutdown_led_sequence()
        else:
            if current_state == State.STOPPED:
                logger.info('Powering up LEDs')
                startup_led_sequence()
                current_state = State.RUNNING
        if moon_off:
            if current_moon_phase != 0:
                handle_phase_select(0)
                current_moon_phase = 0
                logger.info('Shutting down moon')
        else:
            level = int(moon_phase())
            if current_moon_phase != level:
                logger.info('Moving to moon phase {} [{}]'.format(PHASE_NAME[level], level))
                handle_phase_select(level)
                current_moon_phase = level

        await asyncio.sleep(1)


def startup_led_sequence(unused_addr=None):
    handle_background_run_index(None, 1, False)
    handle_background_mode(None, 1)
    handle_power_on()
    time.sleep(1)
    handle_background_mode(None, 2)


def shutdown_led_sequence(unused_addr=None):
    handle_background_run_index(None, 1, False)
    time.sleep(5)
    handle_background_mode(None, 0)
    handle_power_off()


async def init_main(args, dispatcher):
    """ Initialization routine """
    loop = asyncio.get_event_loop()
    logger.info('Serving OSC on {}:{}'.format(args.ip, args.port))
    server = AsyncIOOSCUDPServer((args.ip, args.port), dispatcher, loop)
    transport, _ = await server.create_serve_endpoint()

    await main_loop(args.ledplay_startup, args.disable_sun, args.debug)

    transport.close()


if __name__ == "__main__":

    os.system('hwclock -s')

    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', default='192.168.7.88', help='The ip to listen on')
    parser.add_argument('--port', type=int, default=9999, help='The port to listen on')
    parser.add_argument('--ledplay_ip', default='192.168.7.88', help='The LED Play ip address')
    parser.add_argument('--ledplay_port', type=int, default=1234, help='The port that the LED Play application is listening on')
    parser.add_argument('--ledplay_startup', required=False, type=int, default=60, help='Time to wait before LEDPlay starts up')
    parser.add_argument('--config', required=False, type=str, default='underonesky/supervision.json')
    parser.add_argument('--disable_sun', dest='disable_sun', action='store_true')
    parser.add_argument('--kill_existing', dest='kill_existing', action='store_true')
    parser.add_argument('--test_phases', dest='test_phases', action='store_true')
    parser.add_argument('--debug', dest='debug', action='store_true')
    parser.set_defaults(disable_sun=False, kill_existing=False, debug=False)
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
        max_led_temp = supervision['max_led_temp']
        max_cpu_temp = supervision['max_cpu_temp']
    for pin in phase_pin_numbers:
        phase_pins.append(DigitalOutputDevice(pin))

    errmsg = YRefParam()
    if YAPI.RegisterHub('usb', errmsg) != YAPI.SUCCESS:
        logger.error('YAPI init error ' + errmsg.value)
    else:
        temp_sensor = YTemperature.FirstTemperature()
        if temp_sensor:
            temp_sensor_1 = YTemperature.FindTemperature(temp_sensor.get_module().get_serialNumber() + '.temperature1')
            temp_sensor_2 = YTemperature.FindTemperature(temp_sensor.get_module().get_serialNumber() + '.temperature2')
        else:
            logger.error('No temp sensor connected')
        watchdog = YWatchdog.FirstWatchdog()
        if watchdog:
            if args.debug:
                watchdog.set_running(YWatchdog.RUNNING_OFF)
            else:
                watchdog.resetWatchdog()
        else:
            logger.error('No watchdog connected')

    logger.info('LEDPlay OSC client on {}:{}'.format(args.ledplay_ip, args.ledplay_port))
    led_play = udp_client.UDPClient(args.ledplay_ip, args.ledplay_port)

    dispatcher = Dispatcher()
    dispatcher.map('/supervisor/poweron', handle_power_on)
    dispatcher.map('/supervisor/poweroff', handle_power_off)
    dispatcher.map('/supervisor/moon', handle_test)
    dispatcher.map('/supervisor/full_test', handle_full_test)
    dispatcher.map('/supervisor/led_temp', handle_led_temp)
    dispatcher.map('/supervisor/cpu_temp', handle_cpu_temp)
    dispatcher.map('/supervisor/run_index', handle_background_run_index)
    dispatcher.map('/supervisor/startup_sequence', startup_led_sequence)
    dispatcher.map('/supervisor/shutdown_sequence', shutdown_led_sequence)

    logger.info('Current moon phase is {}'.format(PHASE_NAME[moon_phase()]))
    logger.info('Current sunrise is {}'.format(current_sunrise()))
    logger.info('Current sunset is {}'.format(current_sunset()))

    if args.test_phases:
        while True:
            handle_test()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_main(args, dispatcher))
