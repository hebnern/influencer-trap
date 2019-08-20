import os
import time
import tkinter as tk
import signal
from PIL import ImageTk, Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess

PHOTO_DISPLAY_TIMEOUT = 5 * 60 * 1000

class Handler(FileSystemEventHandler):
    def on_any_event(self, event):
        path = event.dest_path if event.event_type == 'moved' else event.src_path
        self.handle_event(path)

    def handle_event(self, path):
        if not path.endswith('.jpg'):
            return

        try:
            photo = ImageTk.PhotoImage(Image.open(path))
            insta_photo.configure(image=photo)
            insta_photo.image = photo
            display_on()
            global display_off_task
            if display_off_task is not None:
                root.after_cancel(display_off_task)
            display_off_task = root.after(PHOTO_DISPLAY_TIMEOUT, display_off)
        except:
            pass

def check():
    root.after(50, check)

def display_on():
    subprocess.call("xset -display :0.0 dpms force on", shell=True)

def display_off():
    subprocess.call("tvservice -p", shell=True)
    global display_off_task
    display_off_task = None

if __name__ == '__main__':
    cur_dir = os.path.dirname(os.path.realpath(__file__))

    display_off_task = None
    display_off()
    
    root=tk.Tk()
    root.wm_attributes('-fullscreen','true')
    root.config(cursor="none")
    root.after(500, check)

    img = ImageTk.PhotoImage(Image.open(os.path.join(cur_dir, "insta_overlay.png")))
    insta_frame = tk.Label(root, image=img)
    insta_frame.place(x=0, y=0, width=1080, height=1920)

    insta_photo = tk.Label(root)
    insta_photo.place(x=59, y=166, width=951, height=1268)

    event_handler = Handler()

    observer = Observer()
    observer.schedule(event_handler, os.path.join(cur_dir, 'photos'))
    observer.start()

    try:
        root.mainloop()
    finally:
        observer.stop()
        observer.join()
        display_on()
