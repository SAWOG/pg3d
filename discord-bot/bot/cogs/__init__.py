from __future__ import annotations

from discord.ext import commands

from .automod import Automod
from .economy import Economy
from .fun import Fun
from .help import Help
from .invites import Invites
from .levels import Levels
from .mention_guard import MentionGuard
from .moderation import Moderation
from .music import Music
from .roles import Roles
from .server_logs import ServerLogs
from .setup import Setup
from .stats import Stats
from .suggestions import Suggestions
from .tempvoice import TempVoice
from .tickets import Tickets
from .verification import Verification
from .welcome import Welcome
from .youtube import YouTube

ALL_COGS: tuple[type[commands.Cog], ...] = (
    Help,
    Setup,
    Moderation,
    Automod,
    ServerLogs,
    Welcome,
    Roles,
    Verification,
    Tickets,
    Invites,
    Levels,
    Economy,
    Fun,
    TempVoice,
    Stats,
    YouTube,
    Music,
    Suggestions,
    MentionGuard,
)
