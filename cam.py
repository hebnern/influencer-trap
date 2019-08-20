import io
import os
import re
import time
import board
import neopixel
import digitalio
from picamera import PiCamera
import threading
import subprocess


PIXEL_PIN = board.D18
BUTTON_PIN = board.D27
NUM_PIXELS = 92
PIXEL_ORDER = neopixel.GRB


def find_last_match(pattern, string):
    matches = re.finditer(pattern, string, re.MULTILINE)
    if matches:
        return list(matches)[-1]
    return None

class PixelArray(object):
    FLASH_BRIGHTNESS = 0.2
    IDLE_BRIGHTNESS = 0.05

    def __init__(self, pin, num_pixels, pixel_order):
        self.num_pixels = num_pixels
        self.pixel_order = pixel_order
        self.lock = threading.Lock()
        self.pixels = neopixel.NeoPixel(pin, num_pixels, brightness=PixelArray.IDLE_BRIGHTNESS,
                                        auto_write=False, pixel_order=pixel_order)

    def destroy(self):
        self.pixels.deinit()

    def flash_on(self, countdown=True):
        self.lock.acquire()
        self.pixels.brightness = PixelArray.FLASH_BRIGHTNESS

        if countdown:
            for i in range(3):
                self.pixels.fill((255, 0, 0))
                self.pixels.show()
                time.sleep(0.5)
                self.pixels.fill((0, 0, 0))
                self.pixels.show()
                time.sleep(1)

        self.pixels.fill((255, 255, 255))
        self.pixels.show()

    def flash_off(self):
        self.pixels.brightness = PixelArray.IDLE_BRIGHTNESS
        self.pixels.fill((0, 0, 0))
        self.pixels.show()
        self.lock.release()

class IdleAnimation(threading.Thread):
    def __init__(self, pixel_array):
        super(IdleAnimation, self).__init__()
        self.pixel_array = pixel_array
        self.running = False

    def stop(self):
        if self.running:
            self.running = False
            self.join()

    def run(self):
        self.running = True
        def wheel(pos):
            # Input a value 0 to 255 to get a color value.
            # The colours are a transition r - g - b - back to r.
            if pos < 0 or pos > 255:
                r = g = b = 0
            elif pos < 85:
                r = int(pos * 3)
                g = int(255 - pos*3)
                b = 0
            elif pos < 170:
                pos -= 85
                r = int(255 - pos*3)
                g = 0
                b = int(pos*3)
            else:
                pos -= 170
                r = 0
                g = int(pos*3)
                b = int(255 - pos*3)
            return (r, g, b) if self.pixel_array.pixel_order == neopixel.RGB or self.pixel_array.pixel_order == neopixel.GRB else (r, g, b, 0)

        while True:
            for j in range(255):
                if not self.running:
                    return None

                with self.pixel_array.lock:
                    for i in range(self.pixel_array.num_pixels):
                        pixel_index = (i * 256 // self.pixel_array.num_pixels) + j
                        pixel_values = wheel(pixel_index & 255)
                        self.pixel_array.pixels[i] = pixel_values
                    self.pixel_array.pixels.show()

class BigButton(object):
    def __init__(self, pin):
        self.button = digitalio.DigitalInOut(pin)
        self.button.direction = digitalio.Direction.INPUT
        self.button.pull = digitalio.Pull.UP

    def wait_for_press(self):
        while self.button.value:
            time.sleep(0.02)

class Camera(object):
    SETTINGS_UPDATE_INTERVAL = 10 * 60
    
    def __init__(self, resolution, pixel_array):
        self.resolution = resolution
        self.pixel_array = pixel_array
        self.settings_lock = threading.Lock()
        self.update_settings()

    def destroy(self):
        self.settings_update_timer.cancel()

    def update_settings(self):
        print("Updating settings...")
        with self.settings_lock:
            self.pixel_array.flash_on(countdown=False)
            self.settings = self.update_capture_settings()
            self.pixel_array.flash_off()

        print("  Analog gain:", self.settings['analog_gain'])
        print("  Digital gain:", self.settings['digital_gain'])
        print("  Shutter speed:", self.settings['shutter_speed'])
        print("  AWB gains:", self.settings['awb_gains'])

        self.settings_update_timer = threading.Timer(Camera.SETTINGS_UPDATE_INTERVAL, self.update_settings)
        self.settings_update_timer.start()

    def take_photo(self, output_path):
        with self.settings_lock:
            self.pixel_array.flash_on()
            self.capture_image(output_path)
            self.pixel_array.flash_off()

    def update_capture_settings(self):
        raise Exception()

    def capture_image(self, path):
        raise Exception()

class PyCamera(Camera):
    def update_capture_settings(self):
        settings = {
            'analog_gain': None,
            'digital_gain': None,
        }
        with PiCamera(resolution=self.resolution) as camera:
            # Wait for the automatic gain control to settle
            time.sleep(2)

            # Now save the values
            settings['shutter_speed'] = camera.exposure_speed
            settings['awb_gains'] = [float(g) for g in camera.awb_gains]
        return settings

    def capture_image(self, output_path):
        with PiCamera(resolution=self.resolution) as camera:
            camera.exposure_mode = 'off'
            camera.shutter_speed = self.settings['shutter_speed']
            camera.awb_mode = 'off'
            camera.awb_gains = self.settings['awb_gains']
            camera.capture(output_path)
        
class RaspiStillCamera(Camera):
    def update_capture_settings(self):
        cmd = ["raspistill",
               "--width", str(self.resolution[0]),
               "--height", str(self.resolution[1]),
               "--nopreview",
               "--settings"]


        # raspistill hangs if the display is off, so force it on by changing virtual terminals
        subprocess.call("chvt 6", shell=True)
        subprocess.call("chvt 7", shell=True)

        result = subprocess.run(cmd, stderr=subprocess.PIPE)

        # turn display back off
        subprocess.call("tvservice -p", shell=True)

        m1 = find_last_match("mmal: Exposure now (?P<exposure>[0-9]*), analog gain (?P<analog_gain_n>[0-9]*)/(?P<analog_gain_d>[0-9]*), digital gain (?P<digital_gain_n>[0-9]*)/(?P<digital_gain_d>[0-9]*)", str(result.stderr))
        m2 = find_last_match("mmal: AWB R=(?P<awb_r_n>[0-9]*)/(?P<awb_r_d>[0-9]*), B=(?P<awb_b_n>[0-9]*)/(?P<awb_b_d>[0-9]*)", str(result.stderr))

        settings = {
            'analog_gain': float(m1.group('analog_gain_n')) / float(m1.group('analog_gain_d')),
            'digital_gain': float(m1.group('digital_gain_n')) / float(m1.group('digital_gain_d')),
            'shutter_speed': float(m1.group('exposure')),
            'awb_gains': [
                float(m2.group('awb_r_n')) / float(m2.group('awb_r_d')),
                float(m2.group('awb_b_n')) / float(m2.group('awb_b_d')),
            ],
        }

        return settings

    def capture_image(self, output_path):
        subprocess.call(["raspistill",
                         "--output", output_path,
                         "--thumb", "none",
                         "--width", str(self.resolution[0]),
                         "--height", str(self.resolution[1]),
                         "--analoggain", str(self.settings['analog_gain']),
                         "--digitalgain", str(self.settings['digital_gain']),
                         "--exposure", "off",
                         "--shutter", str(self.settings['shutter_speed']),
                         "--awb", "off",
                         "--awbgains", ",".join([str(g) for g in self.settings['awb_gains']]),
                         "--timeout", "1",
                         "--nopreview",
                         "--verbose"])

if __name__ == '__main__':
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    
    try:
        button = BigButton(pin=BUTTON_PIN)
        pixel_array = PixelArray(pin=PIXEL_PIN, num_pixels=NUM_PIXELS, pixel_order=PIXEL_ORDER)
        #camera = PyCamera((951, 1268), pixel_array)
        camera = RaspiStillCamera((951, 1268), pixel_array)

        idle_animation = IdleAnimation(pixel_array)
        idle_animation.start()

        while True:
            print("Waiting for button press")
            button.wait_for_press()
            #time.sleep(5)

            print("Taking a photo")
            camera.take_photo(os.path.join(cur_dir, 'photos', 'photo-%f.jpg' % time.time()))

    finally:
        if camera:
            camera.destroy()
        if idle_animation:
            idle_animation.stop()
        if pixel_array:
            pixel_array.destroy()
    
