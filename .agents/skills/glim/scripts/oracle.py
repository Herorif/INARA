import random
import sys

def roll(dc=10):
    res = random.randint(1, 20)
    print(f"GLiM Oracle: Rolled {res} against DC {dc}. {'SUCCESS' if res >= dc else 'FAILURE'}")

if __name__ == "__main__":
    difficulty = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    roll(difficulty)
