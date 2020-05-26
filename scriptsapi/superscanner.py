#!/usr/bin/env python3
"""
Connects to spectrum server to monitor PSD and detect local increase to pilot channel(s)
"""

import requests, traceback, sys, json, time
import struct, operator
import math
import numpy as np
import websocket
try:
    import thread
except ImportError:
    import _thread as thread
import time

from optparse import OptionParser

import sdrangel

OPTIONS = None
API_URI = None
WS_URI = None
PASS_INDEX = 0
PSD_FLOOR = []
CONFIG = {}

# ======================================================================
class SuperScannerError(Exception):
    def __init__(self, message):
        self.message = message

# ======================================================================
class SuperScannerWebsocketError(SuperScannerError):
    pass

# ======================================================================
class SuperScannerWebsocketClosed(SuperScannerError):
    pass

# ======================================================================
class SuperScannerOptionsError(SuperScannerError):
    pass

# ======================================================================
class SuperScannerAPIError(SuperScannerError):
    pass

# ======================================================================
def get_input_options():

    parser = OptionParser(usage="usage: %%prog [-t]\n")
    parser.add_option("-a", "--address", dest="address", help="SDRangel web base address. Default: 127.0.0.1", metavar="ADDRESS", type="string")
    parser.add_option("-p", "--api-port", dest="api_port", help="SDRangel API port. Default: 8091", metavar="PORT", type="int")
    parser.add_option("-w", "--ws-port", dest="ws_port", help="SDRangel websocket spectrum server port. Default: 8887", metavar="PORT", type="int")
    parser.add_option("-c", "--config-file", dest="config_file", help="JSON configuration file. Mandatory", metavar="FILE", type="string")
    parser.add_option("-j", "--psd-in", dest="psd_input_file", help="JSON file containing PSD floor information.", metavar="FILE", type="string")
    parser.add_option("-J", "--psd-out", dest="psd_output_file", help="Write PSD floor information to JSON file.", metavar="FILE", type="string")
    parser.add_option("-n", "--nb-passes", dest="passes", help="Number of passes for PSD floor estimation. Default: 10", metavar="NUM", type="int")
    parser.add_option("-m", "--margin", dest="margin", help="Margin in dB above PSD floor to detect acivity. Default: 3", metavar="DB", type="int")
    parser.add_option("-f", "--psd-level", dest="psd_fixed", help="Use a fixed PSD floor value.", metavar="FILE", type="float")
    parser.add_option("-X", "--psd-exclude-higher", dest="psd_exclude_higher", help="Level above which to exclude bin scan.", metavar="FILE", type="float")
    parser.add_option("-x", "--psd-exclude-lower", dest="psd_exclude_lower", help="Level below which to exclude bin scan.", metavar="FILE", type="float")
    parser.add_option("-G", "--psd-graph", dest="psd_graph", help="Show PSD floor graphs. Requires matplotlib", action="store_true")
    parser.add_option("-g", "--group-tolerance", dest="group_tolerance", help="Radius (1D) tolerance in points (bins) for hotspots grouping. Default 1.", metavar="FILE", type="int")
    parser.add_option("-r", "--freq-round", dest="freq_round", help="Frequency rounding value in Hz. Default: 1 (no rounding)", metavar="NUM", type="int")
    parser.add_option("-o", "--freq-offset", dest="freq_offset", help="Frequency rounding offset in Hz. Default: 0 (no offset)", metavar="NUM", type="int")

    (options, args) = parser.parse_args()

    if (options.config_file == None):
        raise SuperScannerOptionsError('A configuration file is required. Option -c or --config-file')

    if (options.address == None):
        options.address = "127.0.0.1"
    if (options.api_port == None):
        options.api_port = 8091
    if (options.ws_port == None):
        options.ws_port = 8887
    if (options.passes == None):
        options.passes = 10
    elif options.passes < 1:
        options.passes = 1
    if (options.margin == None):
        options.margin = 3
    if (options.group_tolerance == None):
        options.group_tolerance = 1
    if (options.freq_round == None):
        options.freq_round = 1
    if (options.freq_offset == None):
        options.freq_offset = 0

    return options

# ======================================================================
def on_ws_message(ws, message):
    global PASS_INDEX
    try:
        struct_message = decode_message(message)
        if OPTIONS.psd_fixed is not None and OPTIONS.passes > 0:
            compute_fixed_floor(struct_message)
            OPTIONS.passes = 0 # done
        elif OPTIONS.psd_input_file is not None and OPTIONS.passes > 0:
            global PSD_FLOOR
            with open(OPTIONS.psd_input_file) as json_file:
                PSD_FLOOR = json.load(json_file)
            OPTIONS.passes = 0 # done
        elif OPTIONS.passes > 0:
            compute_floor(struct_message)
            OPTIONS.passes -= 1
            PASS_INDEX += 1
            print(f'PSD floor pass no {PASS_INDEX}')
        elif OPTIONS.passes == 0:
            OPTIONS.passes -= 1
            if OPTIONS.psd_output_file:
                with open(OPTIONS.psd_output_file, 'w') as outfile:
                    json.dump(PSD_FLOOR, outfile)
            if OPTIONS.psd_graph:
                show_floor()
        else:
            scan(struct_message)
    except Exception as ex:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)

# ======================================================================
def on_ws_error(ws, error):
    raise SuperScannerWebsocketError(f'{error}')

# ======================================================================
def on_ws_close(ws):
    raise SuperScannerWebsocketClosed('websocket closed')

# ======================================================================
def on_ws_open(ws):
    print('Starting...')
    def run(*args):
        pass
    thread.start_new_thread(run, ())

# ======================================================================
def decode_message(byte_message):
    struct_message = {}
    struct_message['cf']       = int.from_bytes(byte_message[0:8], byteorder='little', signed=False)
    struct_message['elasped']  = int.from_bytes(byte_message[8:16], byteorder='little', signed=False)
    struct_message['ts']       = int.from_bytes(byte_message[16:24], byteorder='little', signed=False)
    struct_message['fft_size'] = int.from_bytes(byte_message[24:28], byteorder='little', signed=False)
    struct_message['fft_bw']   = int.from_bytes(byte_message[28:32], byteorder='little', signed=False)
    indicators = int.from_bytes(byte_message[32:36], byteorder='little', signed=False)
    struct_message['linear'] = (indicators & 1) == 1
    struct_message['ssb']    = ((indicators & 2) >> 1) == 1
    struct_message['usb']    = ((indicators & 4) >> 2) == 1
    struct_message['samples'] = []
    for sample_index in range(struct_message['fft_size']):
        psd = struct.unpack('f', byte_message[36 + 4*sample_index: 40 + 4*sample_index])[0]
        struct_message['samples'].append(psd)
    return struct_message

# ======================================================================
def compute_fixed_floor(struct_message):
    global PSD_FLOOR
    nb_samples = len(struct_message['samples'])
    PSD_FLOOR = [(OPTIONS.psd_fixed, False)] * nb_samples

# ======================================================================
def compute_floor(struct_message):
    global PSD_FLOOR
    fft_size = struct_message['fft_size']
    psd_samples = struct_message['samples']
    for psd_index, psd in enumerate(psd_samples):
        exclude = False
        if OPTIONS.psd_exclude_higher:
            exclude = psd > OPTIONS.psd_exclude_higher
        if OPTIONS.psd_exclude_lower:
            exclude = psd < OPTIONS.psd_exclude_lower
        if psd_index < len(PSD_FLOOR):
            PSD_FLOOR[psd_index][1] = exclude or PSD_FLOOR[psd_index][1]
            if psd > PSD_FLOOR[psd_index][0]:
                PSD_FLOOR[psd_index][0] = psd
        else:
            PSD_FLOOR.append([])
            PSD_FLOOR[psd_index].append(psd)
            PSD_FLOOR[psd_index].append(exclude)

# ======================================================================
def show_floor():
    import matplotlib
    import matplotlib.pyplot as plt
    print('show_floor')
    plt.figure(1)
    plt.subplot(211)
    plt.plot([x[1] for x in PSD_FLOOR])
    plt.ylabel('PSD exclusion')
    plt.subplot(212)
    plt.plot([x[0] for x in PSD_FLOOR])
    plt.ylabel('PSD floor')
    plt.show()

# ======================================================================
def freq_rounding(freq, round_freq, round_offset):
    shifted_freq = freq - round_offset
    return round(shifted_freq/round_freq)*round_freq + round_offset

# ======================================================================
def scan(struct_message):
    ts = struct_message['ts']
    freq_density = struct_message['fft_bw'] / struct_message['fft_size']
    hotspots = []
    hotspot ={}
    last_hotspot_index = 0
    if struct_message['ssb']:
        freq_start = struct_message['cf']
        freq_stop = struct_message['cf'] + struct_message['fft_bw']
    else:
        freq_start = struct_message['cf'] - (struct_message['fft_bw'] / 2);
        freq_stop = struct_message['cf'] + (struct_message['fft_bw'] / 2);
    psd_samples = struct_message['samples']
    psd_sum = 0
    psd_count = 1
    for psd_index, psd in enumerate(psd_samples):
        freq = freq_start + psd_index*freq_density
        if PSD_FLOOR[psd_index][1]: # exclusion zone
            continue
        if psd > PSD_FLOOR[psd_index][0] + OPTIONS.margin: # detection
            psd_sum += 10**(psd/10)
            psd_count += 1
            if psd_index > last_hotspot_index + OPTIONS.group_tolerance: # new hotspot
                if hotspot.get("begin"): # finalize previous hotspot
                    hotspot["end"] = hotspot_end
                    hotspot["power"] = psd_sum / psd_count
                    hotspots.append(hotspot)
                hotspot = {"begin": freq}
                psd_sum = 10**(psd/10)
                psd_count = 1
            hotspot_end = freq
            last_hotspot_index = psd_index
    if hotspot.get("begin"): # finalize last hotspot
        hotspot["end"] = hotspot_end
        hotspot["power"] = psd_sum / psd_count
        hotspots.append(hotspot)
    process_hotspots(hotspots)

# ======================================================================
def nearest_used_channel(freq):
    channels = CONFIG['channel_info']
    distances = [[abs(channel['frequency'] - freq), channel] for channel in channels if channel['usage'] == 1]
    sorted(distances, key=operator.itemgetter(0))
    if distances:
        return distances[0][1]
    else:
        return None

# ======================================================================
def allocate_channel():
    channels = CONFIG['channel_info']
    for channel in channels:
        if channel['usage'] == 0:
            return channel
    return None

# ======================================================================
def freq_in_ranges_check(freq, freq_ranges):
    for freqrange in freq_ranges:
        if freqrange[0] <= freq <= freqrange[1]:
            return True
    return False

# ======================================================================
def process_hotspots(scanned_hotspots):
    global CONFIG
    if len(scanned_hotspots) > 8: # burst noise TODO: parametrize
        return
    # calculate frequency for each hotspot and create list of valid hotspots
    hotspots = []
    for hotspot in scanned_hotspots:
        width = hotspot['end'] - hotspot['begin']
        fc = hotspot['begin'] + width/2
        fc = freq_rounding(fc, OPTIONS.freq_round, OPTIONS.freq_offset)
        if freq_in_ranges_check(fc, CONFIG['freqrange_exclusions']):
            continue
        hotspot['fc'] = fc
        hotspots.append(hotspot)
    # calculate hotspot distances for each used channel and reuse the channel for the closest hotspot
    channels = CONFIG['channel_info']
    used_channels = [channel for channel in channels if channel['usage'] == 1]
    for channel in used_channels: # loop on used channels
        distances = [[abs(channel['frequency'] - hotspot['fc']), hotspot] for hotspot in hotspots]
        sorted(distances, key=operator.itemgetter(0))
        if distances:
            hotspot = distances[0][1]
            channel['usage'] = 2 # mark channel used on this pass
            channel['frequency'] = hotspot['fc']
            set_channel_frequency(channel)
            hotspots.remove(hotspot) # done with this hotspot
    # for remaining hotspots we need to allocate new channels
    for hotspot in hotspots:
        channel = allocate_channel()
        if channel:
            channel_index = channel['index']
            fc = hotspot['fc']
            print(f'Channel {channel_index} allocated on frequency {fc} Hz')
            channel['usage'] = 2 # mark channel used on this pass
            channel['frequency'] = fc
            set_channel_frequency(channel)
        else:
            print(f'All channels allocated. Cannot process signal at {fc} Hz')
    # cleanup
    for channel in CONFIG['channel_info']:
        if channel['usage'] == 1:   # channel unused on this pass
            channel['usage'] = 0    # release it
            channel_index = channel['index']
            fc = channel['frequency']
            set_channel_mute(channel)
            print(f'Released channel {channel_index} on frequency {fc} Hz')
        elif channel['usage'] == 2:  # channel used on this pass
            channel['usage'] = 1     # reset usage for next pass

# ======================================================================
def set_channel_frequency(channel):
    deviceset_index = CONFIG['deviceset_index']
    channel_index = channel['index']
    channel_id = channel['id']
    channel_frequency = channel['frequency']
    df = channel['frequency'] - CONFIG['device_frequency']
    url = f'{API_URI}/sdrangel/deviceset/{deviceset_index}/channel/{channel_index}/settings'
    payload = {
        sdrangel.CHANNEL_TYPES[channel_id]['settings']: {
            sdrangel.CHANNEL_TYPES[channel_id]['df_key']: df,
            sdrangel.CHANNEL_TYPES[channel_id]['mute_key']: 0
        },
        'channelType': channel_id,
        'direction': 0
    }
    r = requests.patch(url=url, json=payload)
    if r.status_code // 100 != 2:
        raise SuperScannerAPIError(f'Set channel {channel_index} frequency failed')

# ======================================================================
def set_channel_mute(channel):
    deviceset_index = CONFIG['deviceset_index']
    channel_index = channel['index']
    channel_id = channel['id']
    url = f'{API_URI}/sdrangel/deviceset/{deviceset_index}/channel/{channel_index}/settings'
    payload = {
        sdrangel.CHANNEL_TYPES[channel_id]['settings']: {
            sdrangel.CHANNEL_TYPES[channel_id]['mute_key']: 1
        },
        'channelType': channel_id,
        'direction': 0
    }
    r = requests.patch(url=url, json=payload)
    if r.status_code // 100 != 2:
        raise SuperScannerAPIError(f'Set channel {channel_index} mute failed')

# ======================================================================
def get_deviceset_info(deviceset_index):
    url = f'{API_URI}/sdrangel/deviceset/{deviceset_index}'
    r = requests.get(url=url)
    if r.status_code // 100 != 2:
        raise SuperScannerAPIError(f'Get deviceset {deviceset_index} info failed')
    return r.json()

# ======================================================================
def make_config():
    global CONFIG
    with open(OPTIONS.config_file) as json_file: # get base config
        CONFIG = json.load(json_file)
    deviceset_index = CONFIG['deviceset_index']
    deviceset_info = get_deviceset_info(deviceset_index)
    device_frequency = deviceset_info["samplingDevice"]["centerFrequency"]
    CONFIG['device_frequency'] = device_frequency
    for channel_info in CONFIG['channel_info']:
        channel_index = channel_info['index']
        if channel_index < deviceset_info['channelcount']:
            channel_offset = deviceset_info['channels'][channel_index]['deltaFrequency']
            channel_id = deviceset_info['channels'][channel_index]['id']
            channel_info['id'] = channel_id
            channel_info['usage'] = 0 # 0: unused 1: used 2: reused in current allocation step (temporary state)
            channel_info['frequency'] = device_frequency + channel_offset
        else:
            raise SuperScannerAPIError(f'There is no channel with index {channel_index} in deviceset {deviceset_index}')

# ======================================================================
def main():
    try:
        global OPTIONS
        global API_URI
        global WS_URI

        OPTIONS = get_input_options()

        API_URI = f'http://{OPTIONS.address}:{OPTIONS.api_port}'
        WS_URI = f'ws://{OPTIONS.address}:{OPTIONS.ws_port}'

        make_config()

        ws = websocket.WebSocketApp(WS_URI,
                                  on_message = on_ws_message,
                                  on_error = on_ws_error,
                                  on_close = on_ws_close)
        ws.on_open = on_ws_open
        ws.run_forever()

    except SuperScannerWebsocketError as ex:
        print(ex.message)
    except SuperScannerWebsocketClosed:
        print("Spectrum websocket closed")
    except Exception as ex:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)

# ======================================================================
if __name__ == "__main__":
    main()
