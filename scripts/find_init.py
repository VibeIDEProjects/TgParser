"""Find the @main.command right before init_cmd."""
src = open("src/tgparser/cli.py", encoding="utf-8").read()
# Find first "@main.command" that mentions init
i = src.find("def init_cmd")
print("init at", i)
print("---PREV 1500 CHARS---")
print(src[max(0, i-1500):i])
