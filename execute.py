#!/usr/bin/env python3

import sys, os
import argparse
import asyncio
import logging
import time

from contextlib import contextmanager

import yaml

from aioconsole import ainput

from joycontrol import logging_default as log, utils
from joycontrol.command_line_interface import ControllerCLI
from joycontrol.controller import Controller
from joycontrol.controller_state import ControllerState, button_push
from joycontrol.memory import FlashMemory
from joycontrol.protocol import controller_protocol_factory
from joycontrol.server import create_hid_server

logger = logging.getLogger(__name__)

class ScriptOptions(object):
    def __init__(self):
        self.Interval: float = 0.5

    @classmethod
    def fromDict(cls, data):
        Result = cls()
        if "interval" in data:
            Result.Interval = data["interval"]
        return Result

class ScriptExecutor(object):
    def __init__(self):
        self.Options = ScriptOptions()
        self.CtrlState = None

    async def executeNodeRepeat(self, node_dict):
        if "sequence" not in node_dict:
            return

        logger.info("Repeating...")

        if "count" in node_dict:
            for i in range(node_dict["count"]):
                await self.executeSequence(node_dict["sequence"])
        elif "duration" in node_dict:
            Begin = time.time()
            while time.time() - Begin < node_dict["duration"]:
                await self.executeSequence(node_dict["sequence"])
        else:
            while True:
                await self.executeSequence(node_dict["sequence"])

    async def executeNodePress(self, node_dict):
        if "key" in node_dict:
            logger.info(f'Pressing {node_dict["key"]}...')
            await button_push(self.CtrlState, node_dict["key"])
            await asyncio.sleep(self.Options.Interval)

    async def executeNodeSleep(self, sleep_content: float):
        logger.info(f'Sleeping for {sleep_content} seconds...')
        await asyncio.sleep(sleep_content)

    async def executeSequence(self, seq_list):
        for node in seq_list:
            if "press" in node:
                await self.executeNodePress(node["press"])
            elif "repeat" in node:
                await self.executeNodeRepeat(node["repeat"])
            elif "sleep" in node:
                await self.executeNodeSleep(node["sleep"])

async def _main(script, controller, reconnect_bt_addr=None, capture_file=None, spi_flash=None, device_id=None):
    factory = controller_protocol_factory(controller, spi_flash=spi_flash)
    ctl_psm, itr_psm = 17, 19
    transport, protocol = await create_hid_server(factory, reconnect_bt_addr=reconnect_bt_addr, ctl_psm=ctl_psm,
                                                  itr_psm=itr_psm, capture_file=capture_file, device_id=device_id)

    controller_state = protocol.get_controller_state()

    # Create command line interface and add some extra commands
    # cli = ControllerCLI(controller_state)

    print("I'll wait for 10 seconds before executing the sequence.")
    await asyncio.sleep(10)

    Exec = ScriptExecutor()
    Exec.CtrlState = controller_state

    if "options" in script:
        Exec.Options = ScriptOptions.fromDict(script["options"])

    if "sequence" in script:
        await Exec.executeSequence(script["sequence"])

    logger.info('Stopping communication...')
    await transport.close()

if __name__ == '__main__':
    # check if root
    if not os.geteuid() == 0:
        raise PermissionError('Script must be run as root!')

    # setup logging
    #log.configure(console_level=logging.ERROR)
    log.configure()

    parser = argparse.ArgumentParser()
    parser.add_argument('addr', type=str, metavar="ADDR",
                        help='The Switch console Bluetooth address, for '
                        'reconnecting as an already paired controller')
    parser.add_argument('script', type=str, metavar="SCRIPT",
                        help='The script YAML file.')
    parser.add_argument('-l', '--log', metavar="FILE",
                        help="Write hid communication (input reports and "
                        "output reports) to a file.")
    parser.add_argument('-d', '--device-id', dest="device_id", metavar="ID",
                        help='ID of the bluetooth adapter. Integer matching the '
    'digit in the hci* notation (e.g. hci0, hci1, ...) or Bluetooth mac address '
    'of the adapter in string notation (e.g. "FF:FF:FF:FF:FF:FF"). Note: '
    'Selection of adapters may not work if the bluez "input" plugin is enabled.')
    parser.add_argument('--spi-flash', dest="spi_flash", metavar="FILE",
                        help="Memory dump of a real Switch "
                        "controller. Required for joystick emulation. Allows "
                        "displaying of JoyCon colors. Memory dumbs can be created "
                        "using the dump_spi_flash.py script.")
    args = parser.parse_args()

    controller = Controller.PRO_CONTROLLER
    spi_flash = None
    if args.spi_flash:
        with open(args.spi_flash, 'rb') as spi_flash_file:
            spi_flash = FlashMemory(spi_flash_file.read())

    with open(args.script, 'r') as f:
        script = yaml.load(f)

    with utils.get_output(path=args.log, default=None) as capture_file:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            _main(script, controller,
                  reconnect_bt_addr=args.addr,
                  capture_file=capture_file,
                  spi_flash=spi_flash,
                  device_id=args.device_id
                  )
        )
