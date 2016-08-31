#!/usr/bin/python
import math
import os
import glob
import time
import requests
import zerorpc
import threading
import logging
import sys
import gevent
import pickle
import time
import traceback
from datetime import datetime
import Adafruit_CharLCD as LCD

# Setup logging
logging.basicConfig(filename='/usr/bin/tempsensor/sensor.log', filemode='w', level=logging.DEBUG)

# Raspberry Pi configuration:
lcd_rs = 27
lcd_en = 22
lcd_d4 = 25
lcd_d5 = 24
lcd_d6 = 23
lcd_d7 = 18
lcd_red = 5
lcd_green = 17
lcd_blue = 7  # Pin 7 is CE1

# Define LCD column and row size for 20x4 LCD.
lcd_columns = 20
lcd_rows = 4

# Initialize the LCD using the pins
lcd = LCD.Adafruit_RGBCharLCD(lcd_rs, lcd_en, lcd_d4, lcd_d5, lcd_d6, lcd_d7,
                              lcd_columns, lcd_rows, lcd_red, lcd_green, lcd_blue,
                              enable_pwm=True)

# Get saved settings
config = "/usr/bin/tempsensor/config"
tempSettings = pickle.load(open(config, "rb"))
urls = "/usr/bin/tempsensor/urls"
urlConfig = pickle.low(open(urls, "rb"))

# Setup temp sensor
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')
base_dir = '/sys/bus/w1/devices/'
device_folder = glob.glob(base_dir + '28*')[0]
device_file = device_folder + '/w1_slave'

# Create degree simple for lcd screen
lcd.create_char(1, [6,9,9,6,0,0,0,0])

# Thermostat endpoints for node server
class Thermostat(object):
    @staticmethod
    def setPreferredTemp(temp):
        setTemp(temp)
    @staticmethod
    def getPreferredTemp():
        return getTemp()
    @staticmethod
    def setTempMode(mode):
        setMode(mode)
    @staticmethod
    def getTempMode():
        return getMode()
    @staticmethod
    def getCurrTemp():
        return read_temp()['f']
    @staticmethod
    def setPrefFanMode(fanMode):
        setFanMode(fanMode)
    @staticmethod
    def getPrefFanMode():
        getFanMode()

server = zerorpc.Server(Thermostat())
server.bind('tcp://0.0.0.0:4242')

def setTemp(temp):
    global tempSettings
    tempSettings['preferredTemp'] = temp
    logging.info('Setting temp to {}'.format(temp))
    pickle.dump(tempSettings, open(config, "wb"))

def getTemp():
    global tempSettings
    logging.info("Pref Temp: {}".format(tempSettings['preferredTemp']))
    return tempSettings['preferredTemp']

def setFanMode(fanMode):
    global tempSettings
    tempSettings['fanMode'] = fanMode
    logging.info("Setting fan state to: {}".format(fanMode))
    pickle.dump(tempSettings, open(config, "wb"))

def getFanMode():
    global tempSettings
    logging.info("Fan State: {}".format(tempSettings['fanMode']))
    return tempSettings['fanMode']

def getMode():
    global tempSettings
    logging.info("Mode: {}".format(tempSettings['mode']))
    return tempSettings['mode']

def setMode(newMode):
    global tempSettings
    tempSettings['mode'] = newMode
    logging.info('Setting mode to {}'.format(newMode))
    pickle.dump(tempSettings, open(config, "wb"))

def getFanState():
    state = 'auto'
    return state

def getStates(state):
    states = {}
    states['fan'] = state % 10
    state /= 10
    states['cool'] = state % 10
    state /= 10
    states['heat'] = state
    return states

def read_temp_raw():
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines

def read_temp():
    lines = read_temp_raw()
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        temp_f = temp_c * 9.0 / 5.0 + 32.0
        logging.info('{}: Temp read: {}'.format(datetime.now(), temp_f))
        return {'c':temp_c, 'f':temp_f}

def start():
    response = requests.get(urlConfig['status'])
    state = {}
    resp = response.json()
    if 'result' in resp:
        state = getStates(resp['result'])
        if state['fan'] != 0 and tempSettings['mode'] == 'off':
            data = {"params": "off"}
            response = requests.post(urlConfig['url'], data=data)
            resp = response.json()
            if 'return_value' not in resp:
                logging.error('Unable to shut off unit')
                logging.error('Response: {}'.format(response.json()))
    else:
        logging.error('Unabled to get unit status')
    lcd.clear()
    lcd.set_color(0.0, 1.0, 0.0)
    gevent.spawn(server.run)
    lcd.clear()
    lcd.message('Starting up')
    logging.info('Starting up')
    time.sleep(60.0)

def shutDown(running, waiting):
    lcd.clear()
    lcd.set_color(0.0, 1.0, 0.0)
    lcd.message('Shutting Off')
    logging.info('Shutting Off')
    time.sleep(1.0)
    data = {"params": "off"}
    response = requests.post(urlConfig['url'], data=data)
    resp = response.json()
    if resp and 'return_value' in resp.keys() and resp['return_value'] == -1:
        running = False
        wait = time.time()
        waiting = True
        logging.info('Shut off at: {}'.format(datetime.now()))
    else:
        logging.error('Response: {}'.format(response.json()))
    return running, waiting

def stat():
    start()
    wait = time.time()
    waiting = False
    running = False
    while True:
        state = {}
        temp = read_temp()
        preferred = getTemp()
        tempMode = getMode()
        if waiting == False:
            if temp['f'] >= preferred - 1 and tempMode == 'cool':
                if running == False:
                    lcd.clear()
                    lcd.set_color(0.0, 0.0, 1.0)
                    lcd.message('Starting AC')
                    logging.info('Starting AC')
                    time.sleep(1.0)
                    data = {"params": "cool"}
                    response = requests.post(urlConfig['url'], data=data)
                    resp = response.json()
                    if resp and 'return_value' in resp.keys() and resp['return_value'] == 1:
                        response = requests.get(urlConfig['status'])
                        if 'result' in response.json():
                            state = getStates(response.json()['result'])
                            if state['cool'] == 1 and state['fan'] == 1:
                                running = True
                                logging.info('Started cooling at {}'.format(datetime.now()))
                        else:
                            logging.error('Unable to get unit status')
                            logging.error('Response: {}'.format(response.json()))
                    else:
                        logging.error('Response: {}'.format(response.json()))
            elif temp['f'] <= preferred + 1 and tempMode == 'heat':
                if running == False:
                    lcd.clear()
                    lcd.set_color(1.0, 0.0, 0.0)
                    lcd.message('Starting Heater')
                    logging.info('Starting Heater')
                    time.sleep(1.0)
                    data = {"params": "heat"}
                    response = requests.post(urlConfig['url'], data=data)
                    resp = response.json()
                    if resp and 'return_value' in resp.keys() and resp['return_value'] == 0:
                        response = requests.get(urlConfig['status'])
                        if 'result' in response.json():
                            state = getStates(response.json()['result'])
                            if state['heat'] == 1 and state['fan'] == 1:
                                running = True
                                logging.info('Started heating at: {}'.format(datetime.now()))
                        else:
                            logging.error('Unable to get unit status')
                            logging.error('Response: {}'.format(response.json()))
                    else:
                        logging.error('Response: {}'.format(response.json()))
            else:
                if running == True:
                    running, waiting = shutDown(running, waiting)
        else:
            waitTime = time.time()
            remaining = (300 - (waitTime - wait)) / 60
            logging.info('{}: Time remaining: {:.2f} minutes'.format(datetime.now(), remaining))
            if waitTime - wait >= 300:
                waiting = False
        fahrenheit =  '{0:0.2f}'.format(temp['f'])
        lcd.clear()
        lcd.message(fahrenheit + '\x01F')
        time.sleep(1.0)
        gevent.sleep(1)
        logging.info('Running: {}'.format(running))
        logging.info('Waiting: {}'.format(waiting))

try:
    stat()
except:
    logging.error(sys.exc_info()[0])
    logging.error(traceback.format_exc())
    lcd.message('Shutting Off')
    data = {"params": "off"}
    response = requests.post(urlConfig['url'], data=data)
    pickle.dump(tempSettings, open(config, "wb"))
