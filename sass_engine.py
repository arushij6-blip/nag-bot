import random

LEVEL_1_TEMPLATES = [
    "Babe, {task}. By {deadline}. I believe in you. Barely, but I do 🙃",
    "Not to be dramatic but {task} has been staring at me from the to-do list. It's judging us both. {deadline} 👀",
    "Hey so {task} — you gonna do it or should I start a countdown? Deadline: {deadline} ⏰",
    "Cute that you think I forgot about {task}. I didn't. {deadline}. Chop chop 💅",
    "Sooo {task} is still a thing that needs doing. By {deadline}. In case your memory needs a hug 🤗",
    "Dropping this here: {task}. Deadline: {deadline}. Don't make me come back 😘",
    "Quick reminder that {task} won't manifest itself into completion. Trust me, I've tried. {deadline} ✨",
    "You know what would be really attractive? If you'd {task}. By {deadline}. Think about it 😏",
]

LEVEL_2_TEMPLATES = [
    "Okay so I KNOW you saw my last message about {task}. The deadline is {deadline}. Don't play with me 🫠",
    "Me: please {task}. You: *pretends to not see*. The deadline: {deadline}. This relationship: struggling 💔",
    "I'm not saying I'm keeping score, but {task} has been pending since I first asked. {deadline} is RIGHT THERE 📋",
    "If I had a rupee for every time I reminded you to {task}, I'd have enough to hire someone else to do it. {deadline} 💸",
    "POV: you're {task} and you've been ghosted. Deadline {deadline} is feeling very neglected rn 👻",
    "The fact that {task} is still undone is giving 'I'll do it later' energy and later was {deadline} 😤",
    "Babe I love you but I will lose it if I have to remind you about {task} again. DEADLINE: {deadline} 🫡",
    "Just checked — {task} still not done. Also checked — my patience is running low. {deadline} btw 🙄",
    "Google search: how to make husband {task} before {deadline} without committing a crime 🔍",
    "You know the vibe when someone says 'I'll do it' and then doesn't? That's you with {task}. {deadline} 🎭",
]

LEVEL_3_TEMPLATES = [
    "THIRD REMINDER. {task}. {deadline}. I am now emotionally identifying with that dripping faucet because I too am DRIPPING with frustration 🚰😤",
    "Okay I'm drafting two messages rn — one is a reminder to {task} (deadline: {deadline}), the other is to a divorce lawyer. Which one should I send? 💌",
    "I've asked about {task} more times than you've said 'I love you' this month. Deadline was {deadline}. Let that satisfying little fact sink in 📊",
    "Sir. SIR. {task}. The deadline was {deadline}. I have been more patient than a saint and I am NOT a saint 🔥",
    "Imagine explaining to our kids one day that mummy left because daddy wouldn't {task} by {deadline}. The legacy you're building rn is WILD 🏆",
    "Breaking news: Area man achieves the impossible — ignoring THREE reminders to {task}. Deadline {deadline} found dead in a ditch. Thoughts and prayers 📰💀",
    "If ignoring {task} was an Olympic sport, you'd have the gold, silver, AND bronze. Deadline was {deadline}. Standing ovation from absolutely no one 🥇🥈🥉",
    "I asked nicely. I asked firmly. Now I'm asking like someone who knows your mother's phone number and isn't afraid to use it. {task}. {deadline}. NOW 📞",
    "Fun game: what's older — that leftovers in the fridge or the reminder to {task}? Trick question. It's my resentment. {deadline} was AGES ago 🧊",
    "The {task} situation has now been open longer than most Jira tickets at your job and we BOTH know how you feel about those. {deadline} 💻",
    "Day unknown of waiting for you to {task}. I've given up counting. I've given up hope. I have NOT given up nagging. {deadline} WAS the deadline 😩👑",
    "Not to be petty but I timed how long it takes you to open Instagram (3 seconds) vs how long {task} has been pending (since {deadline}). Interesting data 📱📉",
]

COMPLETION_MESSAGES = [
    "Wait... you actually did it? Hold on let me sit down 🪑",
    "AND THE CROWD GOES WILD! He did it! After only *checks notes* three reminders! 🏟️",
    "I'm literally going to frame this moment. Task completed. Screenshot taken. Sending to your mum 📸",
    "Brb updating your Yelp review from 1 star to 1.5 stars ⭐",
    "Look at you doing the bare minimum! I'm so proud I could cry. Actually no, that was from the frustration earlier 😭👏",
    "He did the thing!! Someone get this man a trophy and me a vacation 🏆🏝️",
    "Confirmed done. I'd throw a party but I'm exhausted from all the nagging 🎉😮‍💨",
    "Oh so you CAN do things when asked? Noted. Filing this as evidence for next time 📂",
    "The task is done. The marriage is saved. For now. 💍",
    "Alexa play 'Finally' by CeCe Peniston 🎵",
]


def generate_reminder(task_description: str, reminder_number: int, deadline_str: str) -> str:
    templates = {1: LEVEL_1_TEMPLATES, 2: LEVEL_2_TEMPLATES, 3: LEVEL_3_TEMPLATES}
    pool = templates.get(reminder_number, LEVEL_3_TEMPLATES)
    template = random.choice(pool)
    return template.format(task=task_description.lower(), deadline=deadline_str)


def generate_completion_message(task_description: str) -> str:
    return random.choice(COMPLETION_MESSAGES)
