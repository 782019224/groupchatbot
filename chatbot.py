from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                          CallbackContext, CallbackQueryHandler)
from ChatGPT_HKBU import HKBU_ChatGPT
import configparser
import redis
import logging
import mysql.connector

global redis1
global chatgpt
global sql1

# 全局变量声明（但不初始化）
global redis1, chatgpt, sql1

# 定义奖励规则
REWARDS = {
    20: "话痨小达人",
    40: "故事探险家",
    60: "超级活跃王"
}


def test_mysql_connection():
    try:
        # 尝试连接到数据库
        global sql1
        sql1.ping(reconnect=True)  # 测试连接，如果连接断开则尝试重新连接
        print("MySQL connection is successful!")
    except mysql.connector.Error as err:
        print(f"Failed to connect to MySQL: {err}")
        exit(1)  # 如果连接失败，退出程序
    return sql1


def main():
    # 初始化配置
    config = configparser.ConfigParser()
    config.read('config.ini')

    # 初始化 MySQL
    global sql1
    try:
        sql1 = mysql.connector.connect(
            host=config['MYSQL']['HOST'],
            user=config['MYSQL']['USER'],
            password=config['MYSQL']['PASSWORD'],
            database=config['MYSQL']['DATABASE']
        )
        print("MySQL 连接成功！")
    except Exception as e:
        print(f"MySQL 连接失败: {e}")
        exit(1)

    updater = Updater(token=(config['TELEGRAM']['ACCESS_TOKEN']), use_context=True)
    dispatcher = updater.dispatcher
    # 检查是否成功读取到 [MYSQL] 节
    if 'MYSQL' not in config:
        print("错误: config.ini 中未找到 [MYSQL] 配置节！")
        exit(1)

    global redis1
    redis1 = redis.Redis(host=(config['REDIS']['HOST']),
                         password=(config['REDIS']['PASSWORD']),
                         port=(config['REDIS']['REDISPORT']),
                         decode_responses=(config['REDIS']['DECODE_RESPONSE']),
                         username=(config['REDIS']['USER_NAME']))

    logging.basicConfig(format='%(asctime)s-%(name)s-%(levelname)s -%(message)s',
                        level=logging.INFO)

    test_mysql_connection()

    global chatgpt
    chatgpt = HKBU_ChatGPT(config)

    # Register handlers
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))
    dispatcher.add_handler(CommandHandler("add", add))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("story", start_story))
    dispatcher.add_handler(CallbackQueryHandler(handle_story_branch))
    dispatcher.add_handler(CommandHandler("exit", exit_conversation))
    dispatcher.add_handler(CommandHandler("like", handle_like))
    dispatcher.add_handler(CommandHandler("points", check_points))
    dispatcher.add_handler(CommandHandler("leaderboard", show_leaderboard))  # 添加排行榜命令处理器

    print("Starting the bot...")
    updater.start_polling()
    updater.idle()


def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    cursor = sql1.cursor()

    # 记录用户名到数据库（假设新增一个表 user_info 存储 user_id 和 username 的映射，你可以根据实际情况调整表结构）
    cursor.execute("INSERT INTO user_info (user_id, username) VALUES (%s, %s) ON DUPLICATE KEY UPDATE username = %s",
                   (user_id, username, username))

    # 检查用户是否已存在于活跃度表中
    cursor.execute("SELECT message_count FROM group_activity WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()

    if result:
        # 如果用户已存在，增加消息计数
        new_count = result[0] + 1
        cursor.execute("UPDATE group_activity SET message_count = %s WHERE user_id = %s", (new_count, user_id))
    else:
        # 如果用户不存在，插入新记录
        cursor.execute("INSERT INTO group_activity (user_id, message_count) VALUES (%s, 1)", (user_id,))

    # 增加积分
    add_points(user_id, 1, cursor, update)

    sql1.commit()
    cursor.close()

    # 原有的聊天处理逻辑
    global chatgpt
    user_history = context.user_data.get('history', '')
    user_message = update.message.text
    user_history += f"User: {user_message}\n"

    reply_message = chatgpt.submit(user_history + "AI: ")
    user_history += f"AI: {reply_message}\n"

    context.user_data['history'] = user_history
    update.message.reply_text(reply_message)


def start_story(update: Update, context: CallbackContext) -> None:
    """Start an interactive story in English"""
    user_id = update.message.from_user.id
    cursor = sql1.cursor()
    add_points(user_id, 2, cursor, update)
    sql1.commit()
    cursor.close()

    prompt = """You are an English novelist. Start generating the beginning of an interactive novel with:
    1. An engaging opening paragraph
    2. A crucial decision point
    3. Two short distinct branching options
    4. Show the options in the end of paragraph
    Format:
    [Story opening]
    Option 1: [First option description]
    Option 2: [Second option description]"""

    response = chatgpt.submit(prompt)
    context.user_data['story_history'] = [response]
    context.user_data['branch_count'] = 0

    try:
        story_text = response.split("Option 1:")[0].strip()
        option1 = "① " + response.split("Option 1:")[1].split("Option 2:")[0].strip()
        option2 = "② " + response.split("Option 2:")[1].strip()

        keyboard = [
            [InlineKeyboardButton(option1, callback_data="option1")],
            [InlineKeyboardButton(option2, callback_data="option2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(story_text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Failed to parse story options: {e}")
        update.message.reply_text("Failed to generate story. Please try again.")


def handle_story_branch(update: Update, context: CallbackContext) -> None:
    """Handle story branch selection"""
    user_id = update.callback_query.from_user.id
    cursor = sql1.cursor()
    add_points(user_id, 2, cursor, update.callback_query)
    sql1.commit()
    cursor.close()

    query = update.callback_query
    branch_choice = query.data
    story_history = context.user_data.get('story_history', [])
    branch_count = context.user_data.get('branch_count', 0)

    if branch_count >= 9:
        # 约十个分支后结束故事
        prompt = f"""Conclude this story based on the choices made so far:
        {''.join(story_history)}
        The user chose Option {1 if branch_choice == 'option1' else 2} in the last decision.
        Provide a satisfying ending for the story."""
        response = chatgpt.submit(prompt)
        query.edit_message_text(response)
        context.user_data.clear()
        return

    if branch_choice == 'option1':
        prompt = f"""Continue this story development:
        {story_history[-1]}
        The user chose Option 1. Please:
        1. Develop an unexpected plot twist
        2. Maintain story coherence
        3. Provide two new distinct branching options
        4. Show the options in the end of paragraph
        Format:
        [Story continuation]
        Option 1: [First option description]
        Option 2: [Second option description]"""
    else:
        prompt = f"""Continue this story development:
        {story_history[-1]}
        The user chose Option 2. Please:
        1. Take the story in a different direction
        2. Introduce new elements
        3. Provide two new distinct branching options
        4. Show the options in the end of paragraph
        Format:
        [Story continuation]
        Option 1: [First option description]
        Option 2: [Second option description]"""

    response = chatgpt.submit(prompt)
    story_history.append(response)
    context.user_data['story_history'] = story_history
    context.user_data['branch_count'] = branch_count + 1

    try:
        story_text = response.split("Option 1:")[0].strip()
        option1 = "① " + response.split("Option 1:")[1].split("Option 2:")[0].strip()
        option2 = "② " + response.split("Option 2:")[1].strip()

        keyboard = [
            [InlineKeyboardButton(option1, callback_data="option1")],
            [InlineKeyboardButton(option2, callback_data="option2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(story_text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Failed to parse story options: {e}")
        query.edit_message_text("Failed to advance story. Try starting a new one.")


def help_command(update: Update, context: CallbackContext) -> None:
    """Show help message"""
    help_text = """
    Available commands:
    /story - Start a new interactive story
    /add <keyword> - Track keyword count
    /exit - Reset conversation
    /help - Show this message
    /like - Like a message and earn points
    /points - Check your points
    /leaderboard - Show the user leaderboard
    """
    update.message.reply_text(help_text)


def exit_conversation(update: Update, context: CallbackContext) -> None:
    """Reset conversation"""
    context.user_data.clear()
    update.message.reply_text("Conversation reset successfully")


def add(update: Update, context: CallbackContext) -> None:
    """Handle /add command"""
    try:
        global redis1
        msg = context.args[0]
        redis1.incr(msg)
        update.message.reply_text(f'You have said {msg} for {redis1.get(msg)} times.')
    except (IndexError, ValueError):
        update.message.reply_text('Usage: /add <keyword>')


def handle_like(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    cursor = sql1.cursor()

    # 检查用户是否已存在于积分表中
    cursor.execute("SELECT points, awarded_titles FROM user_points WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()

    if result:
        points = result[0]
        awarded_titles = result[1] if result[1] else ""
        new_points = points + 1
        cursor.execute("UPDATE user_points SET points = %s, awarded_titles = %s WHERE user_id = %s",
                       (new_points, awarded_titles, user_id))
    else:
        new_points = 1
        cursor.execute("INSERT INTO user_points (user_id, points, awarded_titles) VALUES (%s, %s, '')",
                       (user_id, new_points))
        awarded_titles = ""

    check_rewards(user_id, new_points, awarded_titles, cursor, update)
    sql1.commit()
    cursor.close()

    update.message.reply_text("You've liked the message and earned 1 point!")


def check_points(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    cursor = sql1.cursor()

    # 获取用户积分
    cursor.execute("SELECT points, awarded_titles FROM user_points WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()

    if result:
        points = result[0]
        awarded_titles = result[1] if result[1] else ""
        # 获取用户称号
        title = get_title(points, awarded_titles)
        # 获取用户排名
        rank = get_rank(user_id, points, cursor)

        update.message.reply_text(f"你有 {points} 积分，你的称号是：{title}，你的排名是：第 {rank} 名。")
    else:
        update.message.reply_text("你有 0 积分，暂无称号，未进入排名。")

    cursor.close()


def show_leaderboard(update: Update, context: CallbackContext) -> None:
    cursor = sql1.cursor()

    # 获取积分排名
    cursor.execute("SELECT user_id, points FROM user_points ORDER BY points DESC")
    points_leaderboard = cursor.fetchall()

    # 获取活跃度排名（这里假设活跃度以消息计数衡量，你可根据实际情况修改）
    cursor.execute("SELECT user_id, message_count FROM group_activity ORDER BY message_count DESC LIMIT 3")
    activity_leaderboard = cursor.fetchall()

    points_text = "积分排行榜:\n"
    for index, (user_id, points) in enumerate(points_leaderboard, 1):
        points_text += f"{index}. User ID: {user_id}, Points: {points}\n"

    activity_text = "\n活跃度前三名推荐:\n"
    for index, (user_id, _) in enumerate(activity_leaderboard, 1):
        # 根据 user_id 获取 username
        cursor.execute("SELECT username FROM user_info WHERE user_id = %s", (user_id,))
        username_result = cursor.fetchone()
        username = username_result[0] if username_result else "未知用户名"
        activity_text += f"{index}. @{username}\n"

    reply_text = points_text + activity_text
    update.message.reply_text(reply_text)
    cursor.close()


def add_points(user_id, points_to_add, cursor, update_obj):
    cursor.execute("SELECT points, awarded_titles FROM user_points WHERE user_id = %s", (user_id,))
    point_result = cursor.fetchone()
    if point_result:
        points = point_result[0]
        awarded_titles = point_result[1] if point_result[1] else ""
        new_points = points + points_to_add
        cursor.execute("UPDATE user_points SET points = %s, awarded_titles = %s WHERE user_id = %s",
                       (new_points, awarded_titles, user_id))
    else:
        new_points = points_to_add
        cursor.execute("INSERT INTO user_points (user_id, points, awarded_titles) VALUES (%s, %s, '')",
                       (user_id, new_points))
        awarded_titles = ""

    check_rewards(user_id, new_points, awarded_titles, cursor, update_obj)


def check_rewards(user_id, current_points, awarded_titles, cursor, update_obj):
    for reward_points, title in REWARDS.items():
        if current_points >= reward_points and title not in awarded_titles:
            if hasattr(update_obj, 'message'):
                update_obj.message.reply_text(f"恭喜！你已达到 {reward_points} 积分，获得称号：{title}")
            elif hasattr(update_obj, 'edit_message_text'):
                update_obj.edit_message_text(f"恭喜！你已达到 {reward_points} 积分，获得称号：{title}")
            else:
                logging.error(f"Unsupported update object type for sending reward message: {type(update_obj)}")
            # 更新已获得的称号
            new_awarded_titles = awarded_titles + f"{title}," if awarded_titles else f"{title},"
            cursor.execute("UPDATE user_points SET awarded_titles = %s WHERE user_id = %s",
                           (new_awarded_titles, user_id))


def get_title(points, awarded_titles):
    available_titles = []
    for reward_points, title in REWARDS.items():
        if points >= reward_points:
            available_titles.append(title)
    valid_titles = [title for title in available_titles if title in awarded_titles]
    return ", ".join(valid_titles) if valid_titles else "暂无称号"


def get_rank(user_id, points, cursor):
    cursor.execute("SELECT user_id, points FROM user_points ORDER BY points DESC")
    leaderboard = cursor.fetchall()
    rank = 1
    for uid, p in leaderboard:
        if p > points:
            rank += 1
        elif uid == user_id:
            break
    return rank


if __name__ == '__main__':
    main()