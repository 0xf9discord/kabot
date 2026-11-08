"""Text-only personal/group bot. Run with kabot personal examples.text_bot:bot."""

from kabot import Bot, SQLiteStore

bot = Bot(store=SQLiteStore("personal-bot.sqlite3"))


@bot.command("도움말")
def help_command(ctx):
    return "/핑, /안녕 이름, /방문 명령을 사용할 수 있습니다."


@bot.command("핑")
async def ping(ctx):
    return "퐁!"


@bot.command("안녕")
def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"


@bot.command("방문")
def visit(ctx):
    return f"{ctx.store.increment(ctx.scope, 'visits')}번째 방문입니다."
