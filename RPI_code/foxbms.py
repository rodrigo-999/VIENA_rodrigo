#!/usr/bin/python
# -*- coding: utf-8 -*-
# The MIT License (MIT)
# Copyright (c) 2020 Francisco Ferreira da Silva, Pedro Lopes Santos
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# -----------------------------------------------------------------------------
# Acknowledgment: This code is in part copied from the canopen code made by
# Bruno Tibério for the SINAMICS Inverter used in the VIENA project.
# The major difference here is the use of can instead of the canopen protocol.
# Thank you Bruno for your support, even while not in the team!
# -----------------------------------------------------------------------------



#   GENERAL TODO:
#       HIGH PRIORITY TASKS:
#       - Add send message to clear deep discharge
#       - Add message support for IVT-Modular (datasheet in discord) 
#       - Translate errors into readable format
#
#       MEDIUM PRIORITY TASKS:
#       - Re-implement verification of connection to BMS, add system to refresh and retry connection until connected
#       - Mode where 1 message of each type is received instead of printing X messages for Y seconds, to improve user friendliness (?)
#               - Read up on how can.bus.filters works (go see read_object() func) and filter for one of each?
#               - Dictionary for each ID, replace most recent message, print most recent iteration of dict, lock section (mutex) if needed?
#       - Implement auto-config routines (auto debug routine)
#       - Implement final functionality (normal operation routines)
#
#       LOW PRIORITY TASKS:
#       - Make keyboard thread exit successfully (without Ctrl-C displaying an error message)
#       - Refactor write_object_periodic to return a bool and test
#

#   COMPLETED FUNCIONTALITY:
#       - Listener to receive/format all CAN ID messages into readable prints for the user
#       - Modify psend in all bms functions to pMessage object, for ease of use and to reduce local variables needed 
#       - Check if already present functions can be integrated/used in input parsing after pMessage change
#


import asyncio
import textwrap
import can
import paho.mqtt.client as mqtt
import sys
import logging
import time
from time import sleep
import threading
import struct
from collections import namedtuple
from struct import *

import socket

#import pydevd

#pydevd.settrace('192.168.31.150', port=8000, stdoutToServer=True, stderrToServer=True)

#--------------------------------------------------------------------------------------------------


#---------------------------------------- FOXBMS INITIALIZATIONS ----------------------------------
class FOXBMS:
    bus = None
    reader = None
    logger = None
    textlogger = None
    loop = None
    notifier = None
    node  = None # need node? (not using canopen)

    printIDs = [0] # IDs to print from
    pMessage = None # periodic message sent to the bms 
    OPstate = 0 # bms operating state 
    ValidStates = { (0, 8),  # No Request -> Standby 
                    (8, 3),  # Standby -> Normal State
                    #(8, 4),  # Standby -> Charge State
                    (3, 8),  # Normal State -> Standby
                    #(4, 8),  # Charge State -> Standby
                    (8, 0)}  # Standby -> No Request

    _connected = False


    # If DBC file is present, this is not necessary, all codes can be gotten
    # from object dictionary. (No DBC file is going to be used here. To use it, another lib is needed.)
    # DISCLAIMER FOXBMS: Message names in the DBC file can vary from the following tables 
    # in order to be compliant with the 32 character limit of DBC files.
    # Requests to the BMS
    # More info available at:
    # https://iisb-foxbms.iisb.fraunhofer.de/foxbms/gen1/docs/html/latest/getting_started/communicating/communicating.html

    RxMessages = {'Software_Reset' : 0x95,
                  'Debug_Message' : 0x100,
                  'State_Request' : 0x120,
                  'GetReleaseVersion': 0x777}
    
    # Messages BMS sends
    TxMessages = {'MSG_SystemState_0' : 0x110,
                  'MSG_SystemState_1' : 0x111,
                  'MSG_SystemState_2' : 0x112,
                  'MSG_SlaveState_0' : 0x115,
                  'MSG_SlaveState_1' : 0x116,
                  'RecOperatingCurrent' : 0x130,
                  'SOP' : 0x131,
                  'SOC' : 0x140,
                  'SOH' : 0x150,
                  'SOE' : 0x160,
                  'MinMaxCellVoltages' : 0x170,
                  'SOV' : 0x171,
                  'MinMaxCellTemperatures' : 0x180,
                  'Tempering' : 0x190,
                  'Insulation' : 0x1A0,
                  'MovAveragePower_0' : 0x1D0,
                  'MovAveragePower_1' : 0x1D1,
                  'MovAveragePower_2' : 0x1D2,
                  'MovAverageCurrent_0' : 0x1E0,
                  'MovAverageCurrent_1' : 0x1E1,
                  'MovAverageCurrent_2' : 0x1E2,
                  'PackVoltage' : 0x1F0,
                  'Cell_voltage_M0_0' : 0x200,
                  'Cell_voltage_M0_1' : 0x201,
                  'Cell_voltage_M0_2' : 0x202,
                  'Cell_voltage_M0_3' : 0x203,
                  'Cell_voltage_M0_4' : 0x204,
                  'Cell_voltage_M0_5' : 0x205,
                  'Cell_temperature_M0_0' : 0x210,
                  'Cell_temperature_M0_1' : 0x211,
                  'Cell_temperature_M0_2' : 0x212,
                  'Cell_temperature_M0_3' : 0x213,
                  'Cell_voltage_M1_0' : 0x220,
                  'Cell_voltage_M1_1' : 0x221,
                  'Cell_voltage_M1_2' : 0x222,
                  'Cell_voltage_M1_3' : 0x223,
                  'Cell_voltage_M1_4' : 0x224,
                  'Cell_voltage_M1_5' : 0x225,
                  'Cell_temperature_M1_0' : 0x230,
                  'Cell_temperature_M1_1' : 0x231,
                  'Cell_temperature_M1_2' : 0x232,
                  'Cell_temperature_M1_3' : 0x233,
                  'Cell_voltage_M2_0' : 0x240,
                  'Cell_voltage_M2_1' : 0x241,
                  'Cell_voltage_M2_2' : 0x242,
                  'Cell_voltage_M2_3' : 0x243,
                  'Cell_voltage_M2_4' : 0x244,
                  'Cell_voltage_M2_5' : 0x245,
                  'Cell_temperature_M2_0' : 0x250,
                  'Cell_temperature_M2_1' : 0x251,
                  'Cell_temperature_M2_2' : 0x252,
                  'Cell_temperature_M2_3' : 0x253,
                  'Cell_voltage_M3_0' : 0x260,
                  'Cell_voltage_M3_1' : 0x261,
                  'Cell_voltage_M3_2' : 0x262,
                  'Cell_voltage_M3_3' : 0x263,
                  'Cell_voltage_M3_4' : 0x264,
                  'Cell_voltage_M3_5' : 0x265,
                  'Cell_temperature_M3_0' : 0x270,
                  'Cell_temperature_M3_1' : 0x271,
                  'Cell_temperature_M3_2' : 0x272,
                  'Cell_temperature_M3_3' : 0x273,
                  'MSG_ISENS_TRIG' : 0x35B,
                  'IVT_Current' : 0x521,           
                  'IVT_Voltage_1': 0x522,
                  'IVT_Voltage_2': 0x523,
                  'IVT_Voltage_3': 0x524,
                  'IVT_Temperature': 0x525,
                  'IVT_Power': 0x526,
                  'IVT_CoulombCount': 0x527,
                  'IVT_EnergyCount': 0x528}

    # Sent Messages sorted by ID instead of String
    TxMessagesByID = {ID : Object for (Object, ID) in TxMessages.items()} 


    # Dictionary with state requests of bms
    stateRequest = {3: 'Normal', 4 : 'Charge', 8 : 'Standby', 0 : 'No Request'}

    # Dictionary describing foxbms general errors
    # TODO
                 
    # Dictionary describing current state of bms
    currentState = {0x00 : 'Uninitialized', 0x03 : 'Idle', 0x04 : 'Standby', 0x05 : 'Precharge (normal)', 
             0x06 : 'Normal', 0x07 : 'Precharge (charge)', 0x08: 'Charge', 0xF0: 'Error'}

    ### ---- store to csv file inicialization ----

    #Messages with this can IDs will bi stored in a text file
    #in the future implement the changing of this list from comand line
    #storeIDs = [0x110,0x1F0,0x521]
    #storeIDs = [0x110,0x111,0x521,0x170]
    storeIDs = [0x521,0x140,0x212,0x211,0x210,0x232,0x231,0x230]
    storeIndex = 0
    #name of the file where data is stored (in the future have this changeble from the cmd line)
    storeFileName='data_test_temp.csv'

    ### ---- MQTT inicialization ----
    
    broker="192.168.31.50" #pi ip (if ip changes this must be changed) 
    port=8080
    client=mqtt.Client("client_bms",protocol=mqtt.MQTTv5,transport='websockets')
    client.username_pw_set("Viena","fiatelettra")
    client.connect(broker,port)
    
    #MQTT: in order to send other messages over mqtt change the lines bellow and:
    #      - the class of the CAN message where the info comes from.
    #      - addicionaly changes to function "mqtt_handler"  may also be needed

    sendIDs = [0x110,0x140,0x170,0x180,0x1f0,0x521]  #info from this can ids will be sent over mqtt
    
    #dict with mqtt channels used in the interface and the id that should be sent over that channel
    mqttSubChannelsByID = { 0X110: 'state', 0x140: 'soc', 0x170: 'cell_volt',  0x180: 'cell_temp', 0x1f0: 'pack_voltage', 0x521: 'current'}
    
    counter=0 #counter is incremented every time a IVT current message is recived  
    wait=5    #when the counter reaches the value of wait the message is sent 

    def __init__(self, _bus=None, debug=False):
        # check if bus is passed over or create a new one

        # if not _bus:
        #     self.bus = can.interface.Bus(bustype='can0', channel='socketcan', bitrate=500000)
        # else:
        #     self.bus = _bus

        self.logger = logging.getLogger('FOXBMS')
        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

    def log_info(self, message=None):
        """Log a message

        A wrap around logging.
        The log message will have the following structure\:
        [class name \: function name ] message

        Args:
            message: a string with the message.
        """
        if message is None:
            # Do nothing
            return
        self.logger.info('[{0}:{1}] {2}'.format(
            self.__class__.__name__,
            sys._getframe(1).f_code.co_name,
            message))
        return

    def log_debug(self, message=None):
        """Log a message with debug level

        A wrap around logging.
        The log message will have the following structure \:
        [class name \: function name ] message

        the function name will be the caller function retrieved automatically
        by using sys._getframe(1).f_code.co_name

        Args:
            message: a string with the message.
        """
        if message is None:
            # Do nothing
            return
        
        self.logger.debug('[{0}:{1}] {2}'.format(
            self.__class__.__name__,
            sys._getframe(1).f_code.co_name,
            message))
        return

    def begin(self, _channel='can0', _bustype='socketcan', object_dictionary=None):
        """
        Initialize FOXBMS device

        Configure and setup FOXBMS device

        Args:
            nodeID:     Node ID of the device (NEED TO SOLVE THIS ON, NOT CANOPEN)
            _channel (optional):    Port used for communication. Default can0
            _bustype (optional):    Port type used. Default socketcan.
            object_dictionary (optional):   Name of DBC file, is any available.
        Return:
            bool: A boolean if all went ok.
        """
        try:
            self.bus = can.interface.Bus(channel=_channel, bustype=_bustype, bitrate=500000)

            self.reader = can.AsyncBufferedReader()
            self.textlogger = can.Logger("logfile.asc")
            self.store_write_header(self.storeIDs)

            listeners = [ # initializes the message unpacker, keyboard input reader and textlogger as BMS listeners
                #self.print_state_change,
                self.CANunpack,
                self.reader,
                self.textlogger
            ]

            self.loop  = asyncio.get_event_loop()
            self.notifier = can.Notifier(self.bus, listeners, loop=self.loop)
            self._connected = True
            ###
            #val, _ = self.read_state() # test if we really have response or is only connceted to CAN bus
            #if val is None:
            #    self._connected = False

            #subscribe to the topic that the interface is going to send on
            self.client.on_message= self.mqtt_recive_handler
            self.client.loop_start()
            self.client.subscribe("VIENA/mqttController/change_state")
            ###
        except Exception as e:
            self.log_info("Exception caught:{0}".format(str(e)))
            self._connected = False
        finally:
            return self._connected

    def disconnect(self):
        self.notifier.stop()
        self.bus.shutdown()
        self._connected = False
        return

    # --------------------------------------------------------------
    # Callback functions
    # --------------------------------------------------------------
    def print_state_change(self, msg): # currently obsolete, maybe delete?
        """
        Prototype function used to test can communication and read
        the raw CAN messages sent by the BMS.

        Args:
            msg -> a string with the ID of the CAN node to be read.
        """

        if msg.arbitration_id == 0x110: # System State 0
            print(msg)
            data = msg.data[0]

            mask = 0b00000001 
            if (mask & data == 1):
                print('maximum safety limit violated')

            mask = 0b00000010
            if (mask & data == 2):
                print('recommended safety limit violated')

            mask = 0b00000100
            if (mask & data == 4):
                print('maximum operating limit violated')

            state = msg.data[1]
            print('BMS State - {0}'.format(self.currentState.get(state, "Invalid State Request")))

        if msg.arbitration_id == 0x111: # System State 1
            print(msg)
        if msg.arbitration_id == 0x112: # System State 2
            print(msg)
        
        if msg.arbitration_id == 0x200: # Cell Voltage M0_0
            print(msg.data[0])

        
    def CANunpack(self, msg):
        """
        Unpacker function for received CAN messages; 
        Checks what the message contents are, unpacks to data structures according to the
        ID of the message, and sends to the print handler to print the message to terminal. 
        This is used so that the terminal output displays accurate values and their meanings, 
        instead of just printing out the bit contents of the message.

        Args: 
            msg -> CAN message frame sent by BMS
        
        """
        id = msg.arbitration_id # check CAN message ID

        if id in self.TxMessagesByID: # if the ID is known, grab object class from the dictionary
            msgUnpacked = 'Could not decode message'
            if self.TxMessagesByID[id][:9] == 'Cell_volt': # voltage special case, since there are multiple battery voltages
                objclass = globals()['Cell_voltage'](id)         
            elif self.TxMessagesByID[id][:9] == 'Cell_temp': # temperature special case, since there are multiple battery temperatures
                objclass = globals()['Cell_temperature'](id)
            else:
                objclass = globals()[self.TxMessagesByID[id]](id) # general handler, otherwise

            msgUnpacked = objclass.unpacker(msg.data) # unpack the message according to object class

            if self.storeIDs != None:
                self.store_handler(msgUnpacked, id) # if the message is supposed to be stored, store it in a text file

            if self.printIDs != None:
                self.print_handler(msgUnpacked, id) # if the message is supposed to be printed, print it(revise this comment later)
            
            if self.sendIDs != None:
                msgMqtt = objclass.unpacker_mqtt(msg.data) # unpack the message according to object class
                self.mqtt_handler(msgMqtt, id)
    # --------------------------------------------------------------
    # Basic set of functions
    # --------------------------------------------------------------
    def read_object(self, ID): # currently unused
        # useful to understand how to limit the bus to only display messages from a single ID (and use it for such)
        """
        Request a read from BMS node referenced by index and subindex, as indicated in the BMS dictionary.
        After the read is requested, the function waits until it receives a message, and tries to unpack it
        and format it according to the object it read from.
        In case of no message received/timeout, an exception is generated and logged.

        Args:
            ID:  Hexadecimal ID of the CAN node (BMS dictionary object) for which to send a message to
        Returns:
            msg_data:  formatted message string returned by FOXBMS or empty if unsucessful
        """
        if self._connected:
            try:
                filter = [{"can_id": ID, "can_mask": 0x7FF, "extended": False}] # initializes filter with requested ID
                self.bus.set_filters(filters=filter) # sets the filter to only recieve messages from requested ID
                sleep(2) # waits for a message to arrive 
                msg_data = self.bus.recv(timeout=5) # receives message 
                self.CANunpack(msg_data) # unpacks the message using the CAN unpacker
                return msg_data
            except Exception as e:
                self.log_info('Exception caught:{0}'.format(str(e)))
                return None
        else:
            self.log_info(' Error: {0} is not connected'.format(
                self.__class__.__name__))
            return None

    def write_object(self, ID, data): # currently unused since all current sent messages are periodic
        # can be used to request a state change (as opposed to sending multiple equal state change requests)
        """
        Write data to BMS dictionary object referenced by ID.

        Args:
            ID:    hexadecimal ID of the CAN node (BMS dictionary object) for which to send a message to
            data:  byte string corresponding to CAN message data
        Returns:
            bool:  boolean corresponding to if message was sent successfully or not
        """
        if self._connected:
            try:
                msg = can.Message(arbitration_id=ID,data=data)
                self.bus.send(msg,timeout=5)
                return True
            except Exception as e:
                self.log_info('Exception caught:{0}'.format(str(e)))
                return False
        else:
            self.log_info(' Error: {0} is not connected'.format(
                self.__class__.__name__))
            return False

    def write_object_periodic(self, ID, data, period):
        """
        Write data to CAN node (BMS dictionary object) referenced by ID, periodically, according to user-defined period.

        Args:
            ID:    hexadecimal ID of the CAN node (BMS dictionary object) for which to send a message to
            data:  byte string corresponding to CAN message data
            period:  time between message sending (in seconds)
        Returns:
            pMessage:  BMS pMessage object which indicates which message is/was being sent periodically
            (should return bool:  boolean corresponding to if message was defined successfully or not)
        """       
        if self._connected:
            try:
                msg = can.Message(arbitration_id=ID,data=data,is_extended_id=False)
                self.pMessage = self.bus.send_periodic(msg,period,None,True) 
                return self.pMessage # probably doesn't need to return, since it already defines the BMS pmessage above
                # and also redefines it when returning
                # TODO: refactor to return bool, like in write_object(), and test
            except Exception as e:
                self.log_info('Exception caught:{0}'.format(str(e)))
                return None # change to bool here
        else:
            self.log_info(' Error: {0} is not connected'.format(
                self.__class__.__name__))
            return None # change to bool here

    def stop_write_periodic(self):
        """
        Stops periodic sending of previously defined periodic write to CAN node (BMS dictionary object).

        Returns:
            bool:  boolean corresponding to if periodic message was stopped successfully or not
        """ 
        if self._connected:
            try:
                self.pMessage.stop()
                return True
            except Exception as e:
                self.log_info('Exception caught:{0}'.format(str(e)))
                return False                
        else:
            self.log_info(' Error: {0} is not connected'.format(
                self.__class__.__name__))
            return False

    def start_write_periodic(self):
        """
        Starts periodic sending of previously defined periodic write to CAN node (BMS dictionary object).

        Returns:
            bool:   boolean corresponding to if periodic message was started successfully or not
        """
        if self._connected:
            try:
                self.pMessage.start()
                return True
            except Exception as e:
                self.log_info('Exception caught:{0}'.format(str(e)))
                return False                
        else:
            self.log_info(' Error: {0} is not connected'.format(
                self.__class__.__name__))
            return False     

    
    def change_data_periodic(self, data):
        """
        Changes message data of previously defined periodic write to CAN node (BMS dictionary object).

        Args:
            data:   CAN message data to be sent instead of the previously defined periodic message 
        Returns:
            bool:   boolean corresponding to if periodic message was changed successfully or not
        """     
        if self._connected:
            try:
                # the commented code below should work, but doesn't (maybe .modify_data requires message to be stopped first then started again?)
                #msg = can.Message(arbitration_id=int(self.pMessage.can_id),data=data,)
                #self.pMessage.modify_data(msg)

                # so instead we stop the previously sent message and start sending a new one, overwriting the previous
                self.pMessage.stop()
                #self.pMessage = self.write_object_periodic(int(self.pMessage.can_id), data, 0.1)
                self.pMessage = self.write_object_periodic(0x120, data, 0.1)

                return True
            except Exception as e:
                self.log_info('Exception caught:{0}'.format(str(e)))
                return False
        else:
            self.log_info(' Error: {0} is not connected'.format(
                self.__class__.__name__))
            return False

    # --------------------------------------------------------------
    # High level functions
    # --------------------------------------------------------------
    def read_state(self): # currently unused, obsolete
        """
        Read functional state of foxBMS.

        Returns:
            state: None or the current foxBMS state.
            bool: A boolean corresponding to if the state was read successfully or not
        """
        ID = self.TxMessages['MSG_SystemState_0']
        state = self.read_object(ID)
        if not state:
            self.log_info('Error trying to read {0} state'.format(
                self.__class__.__name__))
            return state, False
        
        # return statusword as an int type
        return state[1], True


    def print_state(self): #currently unused, obsolete
        state, OK = self.read_state()

        if OK:
            print('BMS State (Int) - {0}'.format(state))
            print('BMS State - {0}'.format(self.currentState.get(state, "Invalid State Request")))
            

    def set_state(self, state):
        """
        Changes operating state of foxBMS.
        Check BMS object ValidStates for all the possible (or currently implemented) state transitions.

        Returns:
            bool: A boolean corresponding to if the state was changed successfully or not.
        """
        OK = False
        if (self.OPstate, state) in self.ValidStates:
            print('BMS State - {0} - {1}'.format(state, self.stateRequest[state]))
            data = [0,state,0,0,0,0,0,0]
            self.OPstate = state
            OK = self.change_data_periodic(data) # check at a later stage if the stage request needs to be repeated, or can be a single message
        else:
            print("Invalid state change.")

        if not OK:
            return False
        return True


    def check_general_errors(self):
        #TODO
        return
 
    #when mqtt message recived it changes the state 
    #message must be a strting with the desired state 
    def mqtt_recive_handler(self,client,userdata,message):
        print("mqtt message recived")
        if str(message.payload.decode("utf-8")) == '"Normal"':
            #because message recive is "Normal" in the if it must be '"Normal"'
            self.set_state(3)
            

        elif str(message.payload.decode("utf-8")) == '"Standby"':
            self.set_state(8)
            
        return
            
    def print_handler(self, msgUnpacked, msgID):
        """
        Function to handle the formatting and printing of the messages in a format readable and digestible by the user.

        Args:
            msgUnpacked: named tuple containing all the CAN node (BMS dictionary object) unpacked data into appropriate
                fields.
            msgID: ID of the CAN node (BMS dictionary object) whose message is currently being handled
        
        """
        if msgID in self.printIDs or self.printIDs[0] == -1: # if msgID is included in current print filter (can also be implemented with bus.filter)
            print(str() + str(type(msgUnpacked).__name__) + ':') # print name of CAN node being read
            for x in range(len(msgUnpacked)):
                print('\t' + str(msgUnpacked._fields[x]) + ':' + str(msgUnpacked[x])) # print data field names and respective values
            print('\n')

        return

    def store_handler(self, msgUnpacked, msgID): 
        
         
        if msgID == self.storeIDs[self.storeIndex]: # if msgID is the next that must be stored

            f=open( self.storeFileName, 'a')

            if self.storeIndex == 0:
                f.write( str(time.time()) + ',')

            for x in range(len(msgUnpacked)):
                f.write(  str(msgUnpacked[x]) + ',') # store data

            if self.storeIndex == len(self.storeIDs) - 1: #if the end of the storeID list was reached start a new line in the file and start the list from the beginning
                f.write('\n')
                self.storeIndex=0
            else:
                self.storeIndex= self.storeIndex + 1 #update store index to indicate the next ID

            f.close



        return


    def store_write_header(self,storeIDs): 
        # write header with name of data field
        
        f=open( self.storeFileName, 'a')
        f.write( '\n') #start writing in a new line
        f.write('time,')  #collum for time 

        #collums for the parameters  
        for id in storeIDs:

            if self.TxMessagesByID[id][:9] == 'Cell_volt': # voltage special case, since there are multiple battery voltages
                a = globals()['Cell_voltage'](id)         
            elif self.TxMessagesByID[id][:9] == 'Cell_temp': # temperature special case, since there are multiple battery temperatures
                a = globals()['Cell_temperature'](id)
            else:
                a = globals()[self.TxMessagesByID[id]](id) # general handler, otherwise
            
            
            paramString=a.fields.split()
            for param in paramString :
                f.write(  param + ',') 

        f.write('\n')

        f.close
        return

    def mqtt_handler(self, msgToSend, msgID):

        if msgID in self.sendIDs:
            channel="VIENA/mqttController/bms/"+ self.mqttSubChannelsByID[msgID]

            if self.TxMessagesByID[msgID] == 'MSG_SystemState_0':
                translatedMSG=self.currentState[int( float(msgToSend) )] #translate mode valeu into mode name
                self.send( channel ,translatedMSG ) 

            elif self.TxMessagesByID[msgID] == 'SOC':
                self.send( channel , msgToSend)

            elif self.TxMessagesByID[msgID] == 'PackVoltage':
                self.send( channel , msgToSend)

            elif self.TxMessagesByID[msgID] == 'IVT_Current':
                 #because the ivt current CAN message rate is higher than the other parameters only not all messages are sent over mqtt
                 # if all messages are sent the value on the interface will change to fast to be read by the user   
                if self.counter == self.wait: 
                    self.send( channel , msgToSend)
                    self.counter = 0 
                else :
                    self.counter= self.counter + 1

            elif self.TxMessagesByID[msgID] == 'MinMaxCellTemperatures':
                self.send( channel+"/mean" , msgToSend[0])
                self.send( channel+"/min" , msgToSend[1])
                self.send( channel+"/max" , msgToSend[2])
            elif self.TxMessagesByID[msgID] == 'MinMaxCellVoltages' :
                self.send( channel+"/mean" , msgToSend[0])
                self.send( channel+"/min", msgToSend[1])
                self.send( channel+"/max" , msgToSend[2])
            else:
                self.send( channel , msgToSend)
            
        return

    def send_mqtt_dump(self, msgUnpacked, msgID): #currently unused

        if msgID in self.sendIDs:
            self.send('bms',str() + str(type(msgUnpacked).__name__) + ':') # print name of CAN node being read
            for x in range(len(msgUnpacked)):
                self.send( 'bms', str(msgUnpacked._fields[x]) + ':' + str(msgUnpacked[x])) # print data field names and respective values
        return

    def send(self, channel, msg):
        #sends a string over mqtt
        self.client.publish (channel,msg)
        return

# This dictionary is only necessary to define which messages to display in terminal, currently working correctly
# Maybe can be overhauled and re-done with bus.filters to filter the IDs? (only for code efficiency and "prettyness")
# bus.filters can also be used to filter for a specific ID (see read_object)
print_modes = {
    "all" : [-1], 
    "volt": [0x1F0, 0x170, 0x200, 0x201, 0x202, 0x203, 0x204, 0x205, 0x220, 0x221, 0x222, 0x223, 0x224, 0x225, \
        0x240, 0x241, 0x242, 0x243, 0x244, 0x245, 0x260, 0x261, 0x262, 0x263, 0x264, 0x265],
    "avgs": [0x1D0, 0x1D1, 0x1D2, 0x1E0, 0x1E1, 0x1E2],
    "so": [0x131, 0x140, 0x150, 0x160, 0x171],
    "temp": [0x180, 0x210, 0x211, 0x212, 0x213, 0x230, 0x231, 0x232, 0x233, 0x250, 0x251, 0x252, 0x253, 0x270, 0x271, 0x272, 0x273],
    "state": [0x110, 0x111, 0x112],
    "ivt":[0x521]}

#-------------------------------------------- KB INPUT THREAD -------------------------------------------------------
#       This thread is used for async terminal communication. Since the CAN message reading is also async,
#       if we desire input to the program, we cannot have a blocking reading-from-terminal function in the 
#       main thread, otherwise no messages to/from the BMS will be sent/read, hence using a separate thread.
#       
#       The thread is implemented very rudimentarily to explore the possibilities of only key aspects appearing
#       in the terminal for user interaction.
#
#       Keyboard input uses the following syntax:
#       "CODE [SECONDS]", where CODE is a string equal to one of the above dictionary print_modes Keys, and 
#       [SECONDS] is the int/float of the desired interval at which to PRINT messages.
#       Example: "volt 5" to display volt-related status messages for the next 5 seconds.

class KeyboardThread(threading.Thread):
    bms = None

    def __init__(self, input_callback = None, bms = None, name='kbd-input-thread'):
        self.bms = bms
        self.input_callback = input_callback
        super(KeyboardThread, self).__init__(name=name)
        if self.bms != None: #check if bms is connected
            self.start()
        else:
            print("BMS Error: not found")
        

    def run(self):
        try:
            while True:
                # Always runs input thread to check for new input
                self.input_callback(input(), self.bms) #waits to get input + Return
        except KeyboardInterrupt:
            return


def input_parse(inp, bms):
#    Input parse callback function, interprets user input and calls functions/prints to terminal accordingly.
#    The main functionality is allowing the user to define what CAN IDs to print to terminal and for how long.
#     
#    Args:   inp -> input String
#            bms -> BMS object that the program is connected to

    seconds = 1 # time interval

    if inp == "help":
        print(textwrap.dedent("""\
            ----------------------------------------------------------
            Available commands:

                help                    -   displays all available commands  
                changestate [state]     -   changes the BMS state to the requested state
            

            Available print mode commands:

                COMMAND SYNTAX: "MODE [seconds]", ex: "all 0.5"

                all         -   prints all CAN IDs to terminal
                volt        -   prints the CAN IDs related to the Cell Pack Voltages 
                temp        -   prints the CAN IDs related to the Cell Pack Temperatures
                avgs        -   prints the CAN IDs related to the average Current and Power values 
                so          -   prints the CAN IDs related to the SOs
                state       -   prints the CAN IDs related to the foxBMS operating state
                ivt         -   prints the CAN IDs related to the IVT current sensor
            ----------------------------------------------------------
            """
        ))
    elif inp != "":
        args = inp.split()
        if len(args) < 2 or len(args) > 2:
            print("Invalid Input, must have 2 args")

        elif args[0] in print_modes.keys(): # if the print mode option is valid
            bms.printIDs = print_modes[args[0]] # change print modes
            try:
                seconds = int(args[1]) # check if int, then if float
            except ValueError:
                try:
                    seconds = float(args[1])
                except ValueError:
                    print("Invalid print input, 2nd arg must be a number (integer/float)")
            sleep(seconds) # wait for time interval
            bms.printIDs = [0] # stop printing messages
                

        elif args[0] == 'changestate':
            try:
                statebits = int(args[1])
                if statebits not in bms.stateRequest.keys():
                    print("Invalid change state input, 2nd arg must be a valid state:\n")
                    print("No Request: 0, Normal State: 3, Charge State: 4, Standby State: 8\n")
                else:
                    bms.set_state(statebits)
                
            except ValueError:
                print("Invalid change state input, 2nd arg must be a number (integer)")
            
        else:
            print("Invalid Input")
    
    sleep(0.1)
    print(">>>")
    return  







#------------------------------------  CODE BLOCK FOR LISTENER CLASSES  ------------------------------------------
"""
The following code block contains all individual, separate BMS object classes. Since for each object,
the name, number of fields, number of bits per field, unit type (and factor) per field and ID vary,
it is not possible to define all object messages using just a few classes, and still display every
detail of the received message accurately and informatively to the user.

For info on implementation, please read the first, example class to get a description of all the objects of a generic class
and its functioning.

For more info on these object classes, and related message info, please visit the foxBMS gen1 docs: 
https://iisb-foxbms.iisb.fraunhofer.de/foxbms/gen1/docs/html/latest/getting_started/communicating/communicating.html
"""

class Message:
    # Generic message class, serves as base for all other classes.
    def __init__(self, id):
        self.msgName = 'default' # name of the object
        self.fields = 'default' # tuple containing all data fields of the message (ex: temp Mean, temp Max, temp Min)
        self.ID = id # id of the object, according to defined BMS dictionary
        self.unpackStr = '' # bit string defining number of fields and how many bits to unpack to each
        self.factor = 1 # factor of how much a bit is valued in each field
        self.offset = 0 # offset of starting value
        self.unit = '' # unit of the field
        self.unitConversion= 1 # to convert units (exemple: mV to V) before sending over mqtt
        self.mqttMsgIndex=0 #index of the information to be sent over mqtt
        #example:   factor = 0.01, unit = V, each bit is worth 0.01 V
        #           offset = -10, means the scale starts at -10 V instead of 0 V

    def unpacker(self, message):
        # Generic unpacker function, serves as base for all other classes (and is used by most of them)
        msgUnpacked = 'Could not decode message' # base error status message, in case unpacking goes wrong
        auxlist = [str((x * self.factor) + self.offset) + self.unit for x in list(unpack(self.unpackStr, message))]
        # auxlist does the math and formats every bit value into readable values to print after
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist)) # unpacks the values into each field
        return msgUnpacked

    def unpacker_mqtt(self,message):
        # Generic unpacker function, serves as base for all other classes (and is used by most of them)
        # returns info to be sent over mqtt
        msgUnpacked = 'Could not decode message' # base error status message, in case unpacking goes wrong
        auxlist = ["{:.2f}".format((x * self.factor*self.unitConversion) + self.offset) for x in list(unpack(self.unpackStr, message))]
        msgUnpacked =auxlist[self.mqttMsgIndex]
        return msgUnpacked

class MSG_SystemState_0(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MSG_SystemState_0'+'__'+str(hex(self.ID)) 
        self.fields = 'GS0_general_error GS0_current_state \
        GS0_error_overtemp_charge GS0_error_undertemp_charge GS0_error_overtemp_discharge \
        GS0_error_undertemp_discharge GS0_error_overcurrent_charge GS0_error_overcurrent_discharge'
        self.unpackStr = '<BBBBBBBB'
        self.mqttMsgIndex=1 #the "GS0_current_state" is sent over mqtt


class MSG_SystemState_1(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MSG_SystemState_1'+'__'+str(hex(self.ID))
        self.fields = 'GS1_error_overvoltage GS1_error_undervoltage \
        GS1_error_deep_discharge GS1_error_temperature_MCU0 GS1_error_contactor\
        GS1_error_selftest GS1_error_cantiming GS1_current_sensor GS1_balancing_active' #GS1_error_deep_discharge
        self.unpackStr = '<BBBBBBBB'

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxA = list(unpack(self.unpackStr, message))
        auxA.insert(1, auxA[1] & 0b00000111)
        auxA[2] = auxA[2] >> 3
        auxlist = [str((x * self.factor) + self.offset) + self.unit for x in auxA]
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked


class MSG_SystemState_2(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MSG_SystemState_2'+'__'+str(hex(self.ID))
        self.fields = 'GS2_state_cont_interlock GS2_error_insulation\
        GS2_fuse_state GS2_lowCoinCellVolt GS2_error_openWire GS2_daisyChain\
        GS2_plausibilityCheck'
        self.unpackStr = '<HBBBBBB'
    
class MSG_SlaveState_0(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MSG_SlaveState_0'+'__'+str(hex(self.ID))
        self.fields = 'DummyValue'
        self.unpackStr = '<Q'

class MSG_SlaveState_1(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MSG_SlaveState_1'+'__'+str(hex(self.ID))
        self.fields = 'DummyValue'
        self.unpackStr = '<Q'

class RecOperatingCurrent(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'RecOperatingCurrent'+'__'+str(hex(self.ID))
        self.fields = 'RecChargeCurrent RecChargeCurrent_Peak\
        RecDischargeCurrent	RecDischargeCurrent_Peak'
        self.unpackStr = '<HHHH'
        self.factor = 0.1
        self.unit = 'A'

class SOP(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'SOP'+'__'+str(hex(self.ID))
        self.fields = 'MaxChargePower MaxChargePower_Peak\
        MaxDischargePower MaxDischargePower_Peak'
        self.unpackStr = '<HHHH'
        self.factor = 0.1
        self.unit = 'kW'
    

class SOC(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'SOC'+'__'+str(hex(self.ID))
        self.fields = 'SOC_mean SOC_min SOC_max SOC_max_unused'
        self.unpackStr = '<HHHH'
        self.factor = 0.01
        self.unit = '%'


class SOH(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'SOH'+'__'+str(hex(self.ID))
        self.fields = 'DummyValue'
        self.unpackStr = '<Q'

class SOE(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'SOE'+'__'+str(hex(self.ID))
        self.fields = 'DummyValue'
        self.unpackStr = '<Q'

class MinMaxCellVoltages(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MinMaxCellVoltages'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_Cellvolt_mean CAN0_SIG_Cellvolt_min\
        CAN0_SIG_Cellvolt_max CAN0_SIG_ModNumber_volt_min CAN0_SIG_ModNumber_volt_max'
        self.unpackStr = '<HHHBB'
        self.unit = 'mV'
        self.unitConversion = 1/1000

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'+'__'+str(hex(self.ID))
        auxlist = [((x * self.factor) + self.offset) for x in list(unpack(self.unpackStr, message))]
        for x in range(3):
            auxlist[x] = str(auxlist[x]) + self.unit
        for x in [3,4]:
            auxlist[x] = str(auxlist[x])
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked
        
    def unpacker_mqtt(self,message):
        msgUnpacked = ['Could not decode message','','']
        auxlist = [((x * self.factor*self.unitConversion) + self.offset) for x in list(unpack(self.unpackStr, message))]
        for x in range(3):
            msgUnpacked[x] = "{:.2f}".format(auxlist[x])
        return msgUnpacked


class SOV(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'SOV'+'__'+str(hex(self.ID))
        self.fields = 'DummyValue'
        self.unpackStr = '<Q'

class MinMaxCellTemperatures(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MinMaxCellTemperatures'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_Celltemp_mean CAN0_SIG_Celltemp_min\
        CAN0_SIG_Celltemp_max CAN0_SIG_ModNumber_temp_min CAN0_SIG_ModNumber_temp_max'
        self.unpackStr = '<HHHBB'
        self.factor = 0.01
        self.offset = -128.0
        self.unit = '°C'

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxlist = list(unpack(self.unpackStr, message))
        for x in range(3):
            auxlist[x] = str((auxlist[x] * self.factor) + self.offset) + self.unit
        for x in [3,4]:
            auxlist[x] = str(auxlist[x])
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked

    def unpacker_mqtt(self,message):

        msgUnpacked = ['Could not decode message','','']
        auxlist = [((x * self.factor*self.unitConversion) + self.offset) for x in list(unpack(self.unpackStr, message))]
        for x in range(3):
            msgUnpacked[x] = "{:.2f}".format(auxlist[x])
        return msgUnpacked

class Tempering(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'Tempering'+'__'+str(hex(self.ID))
        self.fields = 'CoolingNeeded HeatingNeeded TemperingDemand'
        self.unpackStr = '<BBLxx'

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxlist = [((x * self.factor) + self.offset) for x in list(unpack(self.unpackStr, message))]
        auxlist[2] = hex(auxlist[2])
        auxlist = [str(x) + self.unit for x in auxlist]
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked

class Insulation(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'Insulation'+'__'+str(hex(self.ID))
        self.fields = 'InsulationStatus InsulationValue'
        self.unpackStr = '<BHxxxxx'
        self.unit = 'kOhm'

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxlist = [str((x * self.factor) + self.offset) for x in list(unpack(self.unpackStr, message))]
        auxlist[1] += self.unit
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked

class MovAveragePower_0(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MovAveragePower_0'+'__'+str(hex(self.ID))
        self.fields = 'MovAverage_Power_1s MovAverage_Power_5s'
        self.unpackStr = '<LL'
        self.offset = -2500000
        self.unit = 'W'

class MovAveragePower_1(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MovAveragePower_1'+'__'+str(hex(self.ID))
        self.fields = 'MovAverage_Power_10s MovAverage_Power_30s'
        self.unpackStr = '<LL'
        self.offset = -2500000
        self.unit = 'W'

class MovAveragePower_2(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MovAveragePower_2'+'__'+str(hex(self.ID))
        self.fields = 'MovAverage_Power_60s MovAverage_Power_config'
        self.unpackStr = '<LL'
        self.offset = -2500000
        self.unit = 'W'

class MovAverageCurrent_0(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MovAverageCurrent_0'+'__'+str(hex(self.ID))
        self.fields = 'MovAverage_Current_1s MovAverage_Current_5s'
        self.unpackStr = '<LL'
        self.offset = -2500000
        self.unit = 'mA'

class MovAverageCurrent_1(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MovAverageCurrent_1'+'__'+str(hex(self.ID))
        self.fields = 'MovAverage_Current_10s MovAverage_Current_30s'
        self.unpackStr = '<LL'
        self.offset = -2500000
        self.unit = 'mA'

class MovAverageCurrent_2(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MovAverageCurrent_2'+'__'+str(hex(self.ID))
        self.fields = 'MovAverage_Current_60s MovAverage_Current_config'
        self.unpackStr = '<LL'
        self.offset = -2500000
        self.unit = 'mA'

class PackVoltage(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'PackVoltage'+'__'+str(hex(self.ID))
        self.fields = 'PackVoltage_Battery PackVoltage_PowerNet'
        self.unpackStr = '<LL'
        self.unit = 'mV'
        self.mqttMsgIndex=0 #the "PackVoltage_Battery" is sent over mqtt
        self.unitConversion = 1/1000

class Cell_temperature(Message):
    def __init__(self, id):
        super().__init__(id)
        aux = id & 0x00F
        self.msgName = 'Cell_temperature_M{0}_{1}'.format(int(((id & 0x0F0)-16)/32), aux)+'__'+str(hex(self.ID))
        self.fields = 'Mod0_temp_valid_{0}_{2} Mod0_temp_valid_{0}\
         Mod0_temp_valid_{1} Mod0_temp_valid_{2}'.format(int(aux*3), int(aux*3+1), int(aux*3+2))
        self.unpackStr = '<BHHHx'
        self.factor = 0.01
        self.offset = -128.0
        self.unit = '°C'
    
    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxlist = list(unpack(self.unpackStr, message))
        auxlist[0] = str(auxlist[0])
        for x in [1,2,3]:
            auxlist[x] = str((auxlist[x] * self.factor) + self.offset) + self.unit
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked

class Cell_voltage(Message):
    def __init__(self, id):
        super().__init__(id)
        aux = id & 0x00F
        self.msgName = 'Cell_voltage_M{0}_{1}'.format(int((id & 0x0F0)/32), aux)+'__'+str(hex(self.ID))
        self.fields = 'Mod0_volt_valid_{0}_{2} Mod0_volt_valid_{0}\
         Mod0_volt_valid_{1} Mod0_volt_valid_{2}'.format(int(aux*3), int(aux*3+1), int(aux*3+2))
        self.unpackStr = '<BHHHx'
        self.unit = 'mV'

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxlist = list(unpack(self.unpackStr, message))
        auxlist[0] = str(auxlist[0])
        for x in [1,2,3]:
            auxlist[x] = str((auxlist[x] * self.factor) + self.offset) + self.unit
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked


class MSG_ISENS_TRIG(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'MSG_ISENS_TRIG'+'__'+str(hex(self.ID))
        self.fields = 'ISA_Trigger'
        self.unpackStr = '<Lxxxx'

    def unpacker(self, message):
        msgUnpacked = 'Could not decode message'
        auxlist = list(unpack(self.unpackStr, message))
        auxlist[0] = str(hex(auxlist[0]))
        msgUnpacked = namedtuple(self.msgName, self.fields)._make(tuple(auxlist))
        return msgUnpacked


class IVT_Current(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_Current'+'__'+str(hex(self.ID)) 
        self.fields = 'CAN0_SIG_IVT_Current_MuxID CAN0_SIG_IVT_Current_Status \
        CAN0_SIG_IVT_Current_Measurement'
        self.unpackStr = '>BBi'
        self.unit='mA'
        self.mqttMsgIndex=2 #the "CAN0_SIG_IVT_Current_Measurement" is sent over mqtt
        self.unitConversion = 1/1000



class IVT_Voltage_1(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_Voltage_1'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_Voltage_1_MuxID CAN0_SIG_IVT_Voltage_1_Status \
        CAN0_SIG_IVT_Voltage_1_Measurement'
        self.unpackStr = '>BBI'
        self.unit='mV'

class IVT_Voltage_2(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_Voltage_2'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_Voltage_2_MuxID CAN0_SIG_IVT_Voltage_2_Status \
        CAN0_SIG_IVT_Voltage_2_Measurement'
        self.unpackStr = '>BBI'
        self.unit='mV'

class IVT_Voltage_3(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_Voltage_3'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_Voltage_3_MuxID CAN0_SIG_IVT_Voltage_3_Status \
        CAN0_SIG_IVT_Voltage_3_Measurement'
        self.unpackStr = '>BBI'
        self.unit='mV'

class IVT_Temperature(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_Temperature'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_Temperature_MuxID CAN0_SIG_IVT_Temperature_Status \
        CAN0_SIG_IVT_Temperature_Measurement'
        self.unpackStr = '>BBi'
        self.factor=0.1
        self.unit='C'

class IVT_Power(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_Power'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_Power_MuxID CAN0_SIG_IVT_Power_Status \
        CAN0_SIG_IVT_Power_Measurement'
        self.unpackStr = '>BBi'
        self.unit='W'

class IVT_CoulombCount(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_CoulombCount'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_CC_MuxID CAN0_SIG_IVT_CC_Status \
        CAN0_SIG_IVT_CC_Measurement'
        self.unpackStr = '>BBi'
        self.unit='As'

class IVT_EnergyCount(Message):
    def __init__(self, id):
        super().__init__(id)
        self.msgName = 'CAN0_MSG_IVT_EnergyCount'+'__'+str(hex(self.ID))
        self.fields = 'CAN0_SIG_IVT_EC_MuxID CAN0_SIG_IVT_EC_Status \
        CAN0_SIG_IVT_EC_Measurement'
        self.unpackStr = '>BBi'
        self.unit='Wh'

#------------------------------------ LISTENER CODE BLOCK END ---------------------------------------------


#----------------------------------------------- MAIN -----------------------------------------------------
    
async def main():  

    import argparse
    if sys.version_info < (3, 0):
        print("Please use python version 3")
        return

    # parser initialization, used for initialization of logging
    parser = argparse.ArgumentParser(add_help=True,
                                     description='Test FOXBMS CAN Communication')
    parser.add_argument('--channel', '-c', action='store', default='can0',
                        type=str, help='Channel to be used', dest='channel')
    parser.add_argument('--bus', '-b', action='store',
                        default='socketcan', type=str, help='Bus type', dest='bustype')
    parser.add_argument('--rate', '-r', action='store', default=None,
                        type=int, help='bitrate, if applicable', dest='bitrate')
    #parser.add_argument('--nodeID', action='store', default=2, type=int,
    #                    help='Node ID [ must be between 1- 127]', dest='nodeID')
    #parser.add_argument('--objDict', action='store', default='sinamics_s120.eds',
    #                    type=str, help='Object dictionary file', dest='objDict')
    parser.add_argument("--log-level", action="store", type=str,
                        dest="logLevel", default='info',
                        help='Log level to be used. See logging module for more info',
                        choices=['critical', 'error', 'warning', 'info', 'debug'])
    args = parser.parse_args()


    log_level = {'error': logging.ERROR,
                 'debug': logging.DEBUG,
                 'info': logging.INFO,
                 'warning': logging.WARNING,
                 'critical': logging.CRITICAL
                 }
    # set up logging to file - see previous section for more details
    logging.basicConfig(level=log_level[args.logLevel],
                        format='[%(asctime)s.%(msecs)03d] [%(name)-20s]: %(levelname)-8s %(message)s',
                        datefmt='%d-%m-%Y %H:%M:%S',
                        filename='foxbms.log',
                        filemode='w')

    # define a Handler which writes INFO messages or higher
    console = logging.StreamHandler()
    console.setLevel(log_level[args.logLevel])
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(name)-20s: %(levelname)-8s %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)

    # Initialization of BMS object
    bms = FOXBMS()
    
    
    if not (bms.begin()):
        logging.info('Failed to begin connection with FOXBMS device')
        logging.info('Exiting now')
        return

    kthread = KeyboardThread(input_parse, bms)

    # statusword = bms.read_object(bms.TxMessages['MSG_SystemState_0'])
    # if not statusword:
    #     print("[FOXBMS] Error trying to read FOXBMS statusword\n")
    #     return
    # else:
    #     print('----------------------------------------------------------', flush=True)
    #     print("The statusword is \n {0}".format(statusword))

    # bms.print_state()

    try:

        ID = bms.RxMessages['State_Request']
       
        data = [0,8,0,0,0,0,0,0]

        #data = [0XAA,0,0,0,0,0,0,0] #uncomment to clear deep discharge
        #ID = bms.RxMessages['Debug_Message']


        bms.OPstate = 8 
        bms.pMessage = bms.write_object_periodic(ID, data, 0.1) # requests standby state every 0.1 seconds
        sleep(3)
        print('----------------------------------------------------------', flush=True)
        print("Ctrl+C to exit...\n\n ")
        print('----------------------------------------------------------', flush=True)
        input_parse("help", bms)
        print(">>>")

        while True:
            await bms.reader.get_message()
            await asyncio.sleep(0.5)
            # bms.print_state()
            #data = bms.read_object(0x200)
            #print(bms.bus.filters)
            #print(data)
            #data = bms.read_object(0x110)
            #print(bms.bus.filters)
            #print(data)
            # print("Possible States: \n")
            # print("0 - No Request \n")
            # print("3 - Normal \n")
            # print("4 - Charge \n")
            # print("8 - Standby \n\n")
            # state = int(input('Set State...'))
            # print('----------------------------------------------------------', flush=True)
            # if state is None:
            #     pass
            # else:
            #     print('\nSetting state to {0}\n'.format(bms.stateRequest[state]))
            #     OK = bms.set_state(psend,state)
            # if OK:
            #     bms.print_state()
    except KeyboardInterrupt as e:
        await bms.reader.get_message()
        print('Got {0}\nexiting now'.format(e))
    except ValueError:
        print("Invalid value")
    #except can.CanError:

    finally:
        # inverter.network.sync.stop()
        #psend.stop()
        bms.pMessage.stop()
        bms.disconnect()    

    return


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("exiting... :)")
