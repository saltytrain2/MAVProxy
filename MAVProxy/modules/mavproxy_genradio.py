#!/usr/bin/env python

import time
import socket
import pickle
import string
import random

from MAVProxy.modules.lib import mp_module
from MAVProxy.modules.lib import mp_util
from MAVProxy.modules.lib import mp_settings

if mp_util.has_wxpython:
    from MAVProxy.modules.lib.mp_menu import MPMenuSubMenu, MPMenuItem
    from MAVProxy.modules.mavproxy_map.mp_slipmap import SlipCircle


def gen_id(len=20, chars=string.digits + string.ascii_letters):
    return "".join(random.choice(chars) for _ in range(len))


class SimpleRadioSource():
    '''A simple radio signal following 1/r^2 decay'''

    def __init__(self, latlon):
        self.lat = latlon[0]
        self.lon = latlon[1]
        self.icon = SlipCircle(
            key=gen_id(),
            layer=4,
            latlon=latlon,
            radius=20.0,
            color=(255, 0, 0),
            linewidth=1,
        )

    def distance_from(self, lat, lon):
        return mp_util.gps_distance(self.lat, self.lon, lat, lon)

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, icon):
        self._icon = icon


class GenRadioModule(mp_module.MPModule):
    def __init__(self, mpstate):
        """Initialise module"""
        super().__init__(mpstate, "gen_radio", "Simple Radio Signal Generator")
        self.status_callcount = 0
        self.boredom_interval = 10
        self.last_bored = time.time()

        self.packets_mytarget = 0
        self.packets_othertarget = 0

        self.sock = None
        self.radio_sources = []
        self.last_click = None

        self.example_settings = mp_settings.MPSettings(
            [
                ('verbose', bool, False),
                ('port', int, 45455),
            ]
        )

        self.add_command('genradio', self.cmd_genradio, "simple radio generator", ["<drop|remove|clearall|status>"])

        if mp_util.has_wxpython:
            self.menu = MPMenuSubMenu(
                'GenRadio',
                items=[
                    MPMenuItem('Start', 'Start', '# genradio start'),
                    MPMenuItem('Stop', 'Stop', '# genradio stop'),
                    MPMenuItem('Restart', 'Restart', '# genradio restart'),
                    MPMenuItem('Remove', 'Remove', '# genradio remove'),
                    MPMenuItem('Drop', 'Drop', '# genradio drop'),
                    MPMenuItem('ClearAll', 'ClearAll', '# genradio clearall'),
                ]
            )
            self.module("map").add_menu(self.menu)

        self.start()

    def usage(self):
        '''show help on command line options'''
        return "Usage: genradio <start|stop|restart|status|set|drop|remove|clearall>"

    def cmd_example(self, args):
        '''control behaviour of the module'''
        if len(args) == 0:
            print(self.usage())
        elif args[0] == "status":
            print(self.status())
        elif args[0] == "set":
            self.example_settings.command(args[1:])
        else:
            print(self.usage())

    def drop(self, Source):
        '''drop a radio source on the map'''
        latlon = self.mpstate.click_location
        if self.last_click is not None and self.last_click == latlon:
            return
        self.last_click = latlon
        if latlon is not None:
            radio = Source(latlon)
            self.radio_sources.append(radio)
            d = {
                "action": "add",
                "key": radio.icon.key,
                "lat": latlon[0],
                "lon": latlon[1],
            }
            self.sock.send(pickle.dumps(d))
            self.module("map").map.add_object(radio.icon)

    def clearall(self):
        '''remove all radio sources'''
        for radio in self.radio_sources:
            self.module("map").map.remove_object(radio.icon.key)
        self.radio_sources = []
        d = {
            "action": "clear",
        }
        self.sock.send(pickle.dumps(d))

    def remove(self):
        latlon = self.mpstate.click_location
        if self.last_click is not None and self.last_click == latlon:
            return
        self.last_click = latlon
        self._remove_latlon(latlon)

    def _remove_latlon(self, latlon):
        if latlon is not None:
            closest = None
            closest_distance = 10

            for radio in self.radio_sources:
                if radio.distance_from(latlon[0], latlon[1]) < closest_distance:
                    closest_distance = radio.distance_from(latlon[0], latlon[1])
                    closest = radio

            if closest is not None:
                self.radio_sources.remove(closest)
                self.module("map").map.remove_object(closest.icon.key)
                d = {
                    "action": "remove",
                    "key": closest.icon.key,
                }
                self.sock.send(pickle.dumps(d))
            else:
                print("No suitable radio sources near click")

    def start(self):
        # check if a socket connection is active
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(("127.0.0.1", self.example_settings.port))
        self.sock.settimeout(0.5)

        print(f"Started on port {self.example_settings.port}")

    def stop(self):
        self.clearall()

        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def restart(self):
        self.stop()
        self.start()

    def cmd_genradio(self, args):
        if len(args) == 0:
            print(self.usage())
        elif args[0] == "start":
            self.start()
        elif args[0] == "stop":
            self.stop()
        elif args[0] == "restart":
            self.restart()
        elif args[0] == "set":
            self.example_settings.command(args[1:])
        elif args[0] == "status":
            print(self.status())
        elif args[0] == "drop":
            self.drop(SimpleRadioSource)
        elif args[0] == "remove":
            self.remove()
        elif args[0] == "clearall":
            self.clearall()
        else:
            print(self.usage())

    def status(self):
        '''returns information about module'''
        self.status_callcount += 1
        self.last_bored = time.time() # status entertains us
        return("status called %(status_callcount)d times.  My target positions=%(packets_mytarget)u  Other target positions=%(packets_mytarget)u" %
               {"status_callcount": self.status_callcount,
                "packets_mytarget": self.packets_mytarget,
                "packets_othertarget": self.packets_othertarget,
               })

    def boredom_message(self):
        if self.example_settings.verbose:
            return ("I'm very bored")
        return ("I'm bored")

    def idle_task(self):
        '''called rapidly by mavproxy'''
        if self.sock is not None:
            d = self.sock.recv(1024)
            if not d:
                return
            d = pickle.loads(d)
            if d["action"] == "remove":
                for source in self.radio_sources:
                    if source.icon.key == d["key"]:
                        self.radio_sources.remove(source)
                        self.module("map").map.remove_object(d["key"])

    def mavlink_packet(self, m):
        '''handle mavlink packets'''
        if m.get_type() == 'GLOBAL_POSITION_INT':
            if self.settings.target_system == 0 or self.settings.target_system == m.get_srcSystem():
                self.packets_mytarget += 1
            else:
                self.packets_othertarget += 1


def init(mpstate):
    '''initialise module'''
    return GenRadioModule(mpstate)
