import settings
import bookshelfAPI as c
import time


# Timer function
def timer():
    seconds = 0
    while True:
        time.sleep(1)
        seconds += 1
        print(f"Timer: {seconds} seconds elapsed")
        return seconds


if __name__ == '__main__':
    pass