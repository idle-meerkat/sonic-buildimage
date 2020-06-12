#!/usr/bin/env python

try:
    import os
    import sys
    import importlib
    import time

    sys.path.append(os.path.dirname(__file__))
    import pltfm_mgr_rpc
    from pltfm_mgr_rpc.ttypes import *

    from platform_thrift_client import ThriftClient

    from sonic_platform_base.sfp_base import SfpBase
    from sonic_platform_base.sonic_sfp.sfputilbase import SfpUtilBase
except ImportError as e:
    raise ImportError (str(e) + "- required module not found")

SFP_EEPROM_CACHE = "/var/run/platform/sfp/cache"

class SfpUtil(SfpUtilBase):
    """Platform-specific SfpUtil class"""

    PORT_START = 1
    PORT_END = 0
    PORTS_IN_BLOCK = 0
    QSFP_PORT_START = 1
    QSFP_PORT_END = 0
    EEPROM_OFFSET = 0
    QSFP_CHECK_INTERVAL = 4

    @property
    def port_start(self):
        self.update_port_info()
        return self.PORT_START

    @property
    def port_end(self):
        self.update_port_info()
        return self.PORT_END

    @property
    def qsfp_ports(self):
        self.update_port_info()
        return range(self.QSFP_PORT_START, self.PORTS_IN_BLOCK + 1)

    @property
    def port_to_eeprom_mapping(self):
        print "dependency on sysfs has been removed"
        raise Exception()

    def __init__(self):
        self.ready = False
        self.phy_port_dict = {'-1': 'system_not_ready'}
        self.phy_port_cur_state = {}
        self.qsfp_interval = self.QSFP_CHECK_INTERVAL

        if not os.path.exists(os.path.dirname(SFP_EEPROM_CACHE)):
            try:
                os.makedirs(os.path.dirname(SFP_EEPROM_CACHE))
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

        open(SFP_EEPROM_CACHE, 'ab').close()

        SfpUtilBase.__init__(self)

    def update_port_info(self):
        if self.QSFP_PORT_END == 0:
            with ThriftClient() as client:
                self.QSFP_PORT_END = client.pltfm_mgr.pltfm_mgr_qsfp_get_max_port();
                self.PORT_END = self.QSFP_PORT_END
                self.PORTS_IN_BLOCK = self.QSFP_PORT_END

    def get_presence(self, port_num):
        # Check for invalid port_num
        if port_num < self.port_start or port_num > self.port_end:
            return False

        presence = False

        try:
            with ThriftClient() as client:
                presence = client.pltfm_mgr.pltfm_mgr_qsfp_presence_get(port_num)
        except Exception as e:
            print e.__doc__
            print e.message

        return presence

    def get_low_power_mode(self, port_num):
        # Check for invalid port_num
        if port_num < self.port_start or port_num > self.port_end:
            return False

        with ThriftClient() as client:
            lpmode = client.pltfm_mgr.pltfm_mgr_qsfp_lpmode_get(port_num)
        return lpmode

    def set_low_power_mode(self, port_num, lpmode):
        # Check for invalid port_num
        if port_num < self.port_start or port_num > self.port_end:
            return False

        with ThriftClient() as client:
            status = client.pltfm_mgr.pltfm_mgr_qsfp_lpmode_set(port_num, lpmode)
        return (status == 0)

    def reset(self, port_num):
        # Check for invalid port_num
        if port_num < self.port_start or port_num > self.port_end:
            return False

        with ThriftClient() as client:
            status = client.pltfm_mgr.pltfm_mgr_qsfp_reset(port_num, True)
            status = client.pltfm_mgr.pltfm_mgr_qsfp_reset(port_num, False)
        return status

    def check_transceiver_change(self):
        if not self.ready:
            return

        self.phy_port_dict = {}

        try:
            client = ThriftClient().open()
        except:
            return

        # Get presence of each SFP
        for port in range(self.port_start, self.port_end + 1):
            try:
                sfp_resent = client.pltfm_mgr.pltfm_mgr_qsfp_presence_get(port)
            except:
                sfp_resent = False
            sfp_state = '1' if sfp_resent else '0'

            if port in self.phy_port_cur_state:
                if self.phy_port_cur_state[port] != sfp_state:
                    self.phy_port_dict[port] = sfp_state
            else:
                self.phy_port_dict[port] = sfp_state

            # Update port current state
            self.phy_port_cur_state[port] = sfp_state

        client.close()

    def get_transceiver_change_event(self, timeout=0):
        forever = False
        if timeout == 0:
            forever = True
        elif timeout > 0:
            timeout = timeout / float(1000) # Convert to secs
        else:
            print "get_transceiver_change_event:Invalid timeout value", timeout
            return False, {}

        while forever or timeout > 0:
            if not self.ready:
                try:
                    with ThriftClient(): pass
                except:
                    pass
                else:
                    self.ready = True
                    self.phy_port_dict = {}
                    break
            elif self.qsfp_interval == 0:
                self.qsfp_interval = self.QSFP_CHECK_INTERVAL

                # Process transceiver plug-in/out event
                self.check_transceiver_change()

                # Break if tranceiver state has changed
                if bool(self.phy_port_dict):
                    break

            if timeout:
                timeout -= 1

            if self.qsfp_interval:
                self.qsfp_interval -= 1

            time.sleep(1)

        return self.ready, self.phy_port_dict

    def _get_port_eeprom_path(self, port_num, devid):
        eeprom_path = None

        with ThriftClient() as client:
            presence = client.pltfm_mgr.pltfm_mgr_qsfp_presence_get(port_num)
            if presence == True:
                eeprom_cache = open(SFP_EEPROM_CACHE, 'wb')
                eeprom_hex = client.pltfm_mgr.pltfm_mgr_qsfp_info_get(port_num)
                eeprom_raw = bytearray.fromhex(eeprom_hex)
                eeprom_cache.write(eeprom_raw)
                eeprom_cache.close()
                eeprom_path = SFP_EEPROM_CACHE

        return eeprom_path

class Sfp(SfpBase):
    """Platform-specific Sfp class"""

    sfputil = SfpUtil()

    @staticmethod
    def port_start():
        return Sfp.sfputil.port_start

    @staticmethod
    def port_end():
        return Sfp.sfputil.port_end

    @staticmethod
    def qsfp_ports():
        return Sfp.sfputil.qsfp_ports()

    @staticmethod
    def get_transceiver_change_event(timeout=0):
        return Sfp.sfputil.get_transceiver_change_event()

    def __init__(self, port_num):
        self.port_num = port_num
        SfpBase.__init__(self)

    def get_presence(self):
        return Sfp.sfputil.get_presence(self.port_num)

    def get_lpmode(self):
        return Sfp.sfputil.get_low_power_mode(self.port_num)

    def set_lpmode(self, lpmode):
        return Sfp.sfputil.set_low_power_mode(self.port_num, lpmode)

    def reset(self):
        return Sfp.sfputil.reset(self.port_num)

    def get_transceiver_info(self):
        return Sfp.sfputil.get_transceiver_info_dict(self.port_num)

    def get_transceiver_bulk_status(self):
        return Sfp.sfputil.get_transceiver_dom_info_dict(self.port_num)

    def get_transceiver_threshold_info(self):
        return Sfp.sfputil.get_transceiver_dom_threshold_info_dict(self.port_num)

    def get_change_event(self, timeout=0):
        return Sfp.get_transceiver_change_event(timeout)
