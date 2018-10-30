# This program for an nRF52840 or nRF52832 sends a string on the radio to another node
# Start program by typing:
# start()
# at the REPL >>> prompt.
#
# Then, send a string by typing
# send(theString)
# at the REPL >>> prompt.

# You can use:
# ampy --port /dev/ttyACM0 put main.py
# from LINUX to load main.py onto a nRF52 board

from micropython import const  # needed to efficiently access memory by avoiding micropython lookups
import machine  # so can peek and poke different registers on the nRF5x
import uctypes # needed to create the radio buffer (a byte array)
import utime # needed to create delays
import gc #import garbage collector
import uhashlib # needed for SHA-256
import ubinascii # needed to convert the SHA-256 result into a string

radioBuffer_size = 256
radioBuffer = bytearray(radioBuffer_size)  # allocate IO buffer for use by nRF5x radio
radioBuffer_address = uctypes.addressof(radioBuffer)

target_prefixAddress = const(0xAA)
target_baseAddress = const(0xDEADBEEF)



NRF_POWER = const(0x40000000)
DCDCEN = const(0x578)
NRF_POWER___DCDCEN = const(NRF_POWER + DCDCEN)

NRF_CLOCK = const(0x40000000)
TASKS_HFCLKSTART = const(0)
EVENTS_HFCLKSTARTED = const(0x100)
NRF_CLOCK___TASKS_HFCLKSTART = const(NRF_CLOCK + TASKS_HFCLKSTART)
NRF_CLOCK___EVENTS_HFCLKSTARTED = const(NRF_CLOCK + EVENTS_HFCLKSTARTED)

NRF_RADIO = const(0x40001000)
BASE0 = const(0x51C)
PREFIX0 = const(0x524)
FREQUENCY = const(0x508)
PCNF1 = const(0x518)
PCNF0 = const(0x514)
MODE = const(0x510)
MODECNF0 = const(0x650)
CRCCNF = const(0x534)
PACKETPTR = const(0x504)
RXADDRESSES = const(0x530)
TXPOWER = const(0x50C)
TASKS_DISABLE = const(0x010)
STATE = const(0x550)
TASKS_TXEN = const(0)
EVENTS_READY = const(0x100)
TASKS_START = const(0x008)
EVENTS_END = const(0x10C)
NRF_RADIO___BASE0 = const(NRF_RADIO + BASE0)
NRF_RADIO___PREFIX0 = const(NRF_RADIO + PREFIX0)
NRF_RADIO___FREQUENCY = const(NRF_RADIO + FREQUENCY)
NRF_RADIO___PCNF1 = const(NRF_RADIO + PCNF1)
NRF_RADIO___PCNF0 = const(NRF_RADIO + PCNF0)
NRF_RADIO___MODE = const(NRF_RADIO + MODE)
NRF_RADIO___MODECNF0 = const(NRF_RADIO + MODECNF0)
NRF_RADIO___CRCCNF = const(NRF_RADIO + CRCCNF)
NRF_RADIO___PACKETPTR = const(NRF_RADIO + PACKETPTR)
NRF_RADIO___RXADDRESSES = const(NRF_RADIO + RXADDRESSES)
NRF_RADIO___TXPOWER = const(NRF_RADIO + TXPOWER)
NRF_RADIO___TASKS_DISABLE = const(NRF_RADIO + TASKS_DISABLE)
NRF_RADIO___STATE = const(NRF_RADIO + STATE)
NRF_RADIO___TASKS_TXEN = const(NRF_RADIO + TASKS_TXEN)
NRF_RADIO___EVENTS_READY = const(NRF_RADIO + EVENTS_READY)
NRF_RADIO___TASKS_START = const(NRF_RADIO + TASKS_START)
NRF_RADIO___EVENTS_END = const(NRF_RADIO + EVENTS_END)

def initializeSerialOutput():
    print("Starting...")

def initializeHardware():  # enable the DCDC voltage regulator
    machine.mem32[NRF_POWER___DCDCEN] = 1  # NRF_POWER->DCDCEN=1;   
    
def initializeClocks():    # activate the high frequency crystal oscillator
    # NRF_CLOCK->TASKS_HFCLKSTART=1;  
    machine.mem32[NRF_CLOCK___TASKS_HFCLKSTART] = 1 
    # wait until high frequency clock start is confirmed
    # while (NRF_CLOCK->EVENTS_HFCLKSTARTED==0) {};  
    while (machine.mem32[NRF_CLOCK___EVENTS_HFCLKSTARTED] == 0):
        True
        
def initializeRadio():
    # print target address in hexadecimal
    print("Target address is 0x{:02X}".format(target_prefixAddress)
          + "{:08X}".format(target_baseAddress))
          
    machine.mem32[NRF_RADIO___BASE0] = target_baseAddress
    machine.mem32[NRF_RADIO___PREFIX0] = target_prefixAddress
    
    # value must be between 0 and 100
    machine.mem32[NRF_RADIO___FREQUENCY] = 98  # 2498Mhz.  
    
    # Enable data whitening.
    # Base address is 4 bytes long (possible range is 2 to 4) and 
    # max size of payload is 255,and 0 bytes of static length payload
    machine.mem32[NRF_RADIO___PCNF1] = 0x400FF  # 0x020400FF
    # Use 8-bit preamble, and LENGTH can be 8 bits long.  S0 and S1 are all zero bits long.
    machine.mem32[NRF_RADIO___PCNF0] = 0x00000008
    
    machine.mem32[NRF_RADIO___MODE] = 0  # set 1Mbps datarate.
    machine.mem32[NRF_RADIO___MODECNF0] = 1  # enable fast ramp-up of radio from DISABLED state.
    
    machine.mem32[NRF_RADIO___CRCCNF] = 3  # CRC will be 1 (3 is max)  bytes and is computed including the address field
    machine.mem32[NRF_RADIO___PACKETPTR] = radioBuffer_address  # pointer to the payload in radioBuffer
    
    machine.mem32[NRF_RADIO___RXADDRESSES] = 1  # receive on logical address 0.  Not important for transmitting.
    machine.mem32[NRF_RADIO___TXPOWER] = 8  # set to 8db transmit power, which is the maximum. 
    
    machine.mem32[NRF_RADIO___TASKS_DISABLE] = 1  # DISABLE the radio to establish a known state.
    while (machine.mem32[NRF_RADIO___STATE] != 0):  # wait until radio is DISABLED (i.e. STATE=0);
        True
        
    machine.mem32[NRF_RADIO___TASKS_TXEN] = 1  # turn on the radio transmitter and shift into TXIDLE.
    while (machine.mem32[NRF_RADIO___EVENTS_READY] == 0):  # Busy-wait.  After event READY, radio shall be in state TXIDLE.
        True    
    # ASSERTION: now ready to transmit a packet.

def copyStringToRadioBuffer(theString):
    stringLength=len(theString)
    i=0
    while (i<stringLength):
        radioBuffer[i]=ord(theString[i])
        i=i+1
    radioBuffer[i]=0  # delimit the end of the string
    print(i, " characters copied to transmit buffer.")

def copyStringToRadioBuffer(theString):
    i = 0
    stringLength = len(theString)
    if (stringLength > 0):
        maxIndex = stringLength - 1
        while (i <= maxIndex):
            radioBuffer[i] = ord(theString[i])
            i = i + 1
    radioBuffer[i] = 0
    


#def copyStringSubsetToRadioBuffer(thePayloadCounter,theString,startIndex,stopIndex):
    # startIndex must be less than or equal to stopIndex
    #payloadCounterString =  ("{:>10}".format(str(thePayloadCounter)))
    #i=startIndex
    #j=0
    #txString = payloadCounterString + theString
    #indexLimit = stopIndex + 10
    #while (i<=indexLimit):
    #    if (j<10):
    #        radioBuffer[j]=ord(theString[j])
    #    else:
    #        radioBuffer[j]=ord(theString[i])
    #        i = i + 1 
    #    j = j + 1
    #radioBuffer[j] = 0  # delimit end of string with a zero

def sendShortStrings(payloadCounter,theString,maxSubStringLength):
    stringLength = len(theString)
    if (stringLength > 0):
        index = 0
        maxIndex = stringLength + 1
        while (index<maxIndex):
            stopIndex = index + maxSubStringLength  
            if (stopIndex > maxIndex):
                stopIndex = maxIndex
            payloadCounter = payloadCounter + 1
            #print("payloadCounter=", payloadCounter)
            payloadCounterString =  ("{:<10}".format(str(payloadCounter)))
            #print("payloadCounterString = ", payloadCounterString)
            stringSubset = theString[index:stopIndex]
            txString=payloadCounterString + stringSubset
            #print("txString = ", txString)
            copyStringToRadioBuffer(txString)
            index = stopIndex 
            #print("Radio Buffer = ", radioBuffer)
            for x in [1,2,3]:  #transmit the same payload 3 times to make sure that it gets through
                machine.mem32[NRF_RADIO___EVENTS_END] = 0
                while (machine.mem32[NRF_RADIO___EVENTS_END] != 0): True  # wait
                machine.mem32[NRF_RADIO___TASKS_START] = 1  # Move from TXIDLE mode into TX mode to transmit the packet
                while (machine.mem32[NRF_RADIO___EVENTS_END] == 0): True  # busy-wait until packet is sent
                utime.sleep_ms(100)  # sleep for a second after transmitting the line to give the receiver time to process the  line               
                print (x, " transmitted: ", txString)

        return payloadCounter


def send(theString):
    # if (len(theString)>(radioBuffer_size - 1)):  # if string to be transmitted is too long
        # theString = theString[0:radioBuffer_size] # then cut it down the maximum length allowed
    copyStringToRadioBuffer(theString)
    print("Radio Buffer = ", radioBuffer)
    machine.mem32[NRF_RADIO___EVENTS_END] = const(0)
    machine.mem32[NRF_RADIO___TASKS_START] = 1  # Move from TXIDLE mode into TX mode to transmit the packet
    while (machine.mem32[NRF_RADIO___EVENTS_END] == const(0)): True  # busy-wait until packet is sent
    print ("Finished transmitting: " + theString)


def printFile(theFileName):
    f=open(theFileName)
    lineOfFile = f.read()
    while lineOfFile:
        print(lineOfFile)
        lineOfFile = f.read()
    f.close()

def transmit():
    start()
    theFile="update.txt"
    payloadCounter = 0 #each payload is numbered
    f=open(theFile)
    line = f.readline()
    while (line):
        payloadCounter=sendShortStrings(payloadCounter,line,20)
        print(line)
        gc.collect()
        #print("Memory allocated:  ", gc.mem_alloc())
        #print("Memory free:  ", gc.mem_free())
        #gc.collect()
        #utime.sleep_ms(500)  # sleep for a second after transmitting the line to give the receiver time to process the  line
        line = f.readline()
    f.close()
    
    payloadCounter=sendShortStrings(payloadCounter,"$$$$$$$$",20)
    theHash = computeFileHash(theFile)
    #printFile("update.txt")
    #printFile("update.txt")
    #printFile("update.txt")
    #printFile("update.txt")
    #printFile("update.txt")
    #testSha()
    # sendShortStrings(theHash,20)
    payloadCounter=sendShortStrings(payloadCounter,theHash,20)
    payloadCounter=sendShortStrings(payloadCounter,"$!$!$!$!",20)
    #printFile("update.txt")
    #printFile("update.txt")
    #printFile("update.txt")
    #printFile("update.txt")
    #printFile("update.txt")
    #sendShortStrings("$!$!$!$!",20)

def computeFileHash(theFile):
    f=open(theFile)
    theHash = uhashlib.sha256()
    line = f.readline()
    while line:
        theHash.update(line)
        line = f.readline()
    theRawHash = theHash.digest() # type is 'bytes'
    hexHash =  ubinascii.hexlify(theRawHash) # still 'bytes', but now in hex
    return hexHash.decode()  # hexHash coverted to a string type   

    
def initializeEverything():
    # Main setup    
    initializeSerialOutput()
    initializeHardware()
    initializeClocks()
    initializeRadio() 

def start():
    initializeEverything()
    print("Ready to transmit.")

def testSha():
    initializeEverything()
    theHash=computeFileHash("update.txt")
    print("Sha-256 has is", theHash)
    sendShortStrings(theHash,20)
    sendShortStrings("$!$!$!$!",20)
    print("Done transmitting sha-256")



   
