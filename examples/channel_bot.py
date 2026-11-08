from kabot import Bot, SQLiteStore, quick_reply, text

bot = Bot(store=SQLiteStore("bot.sqlite3"))


@bot.command("도움말")
def help(ctx):
    return text("/안녕 이름, /방문, /메모 내용, /메모확인").with_quick_replies(
        quick_reply("인사", "/안녕 친구"), quick_reply("방문 횟수", "/방문")
    )


@bot.command("안녕")
def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"


@bot.command("방문")
def visit(ctx):
    count = ctx.store.increment(ctx.scope, "visits")
    return f"{count}번째 방문입니다."


@bot.command("메모")
def memo(ctx):
    if not ctx.args:
        return "사용법: /메모 기억할 내용"
    ctx.store.set(ctx.scope, "memo", ctx.args, ttl=86400)
    return "하루 동안 기억할게요."


@bot.command("메모확인")
def read_memo(ctx):
    return ctx.store.get(ctx.scope, "memo", "저장한 메모가 없어요.")
