import discord
from collections import defaultdict
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from discord.ui import View, Select, Button
from flask import Flask
import threading
import io
import os
from threading import Thread
import time

# --- Flask app pour keep-alive ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()



# --- Discord Bot setup ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

ticket_config = {}

# === UI CLASSES ===

class CloseButton(Button):
    def __init__(self):
        super().__init__(label="🔒 Fermer le ticket", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔒 Fermeture du ticket...", ephemeral=True)

        messages = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.content}")

        transcript = "\n".join(messages)
        buffer = io.StringIO(transcript)
        buffer.seek(0)

        guild_id = interaction.guild.id
        log_channel_id = ticket_config[guild_id]["log_channel"]
        log_channel = bot.get_channel(log_channel_id)

        embed = discord.Embed(
            title="📄 Transcript du ticket",
            description=f"Salon fermé : {interaction.channel.name}",
            color=0x95a5a6,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Ticket clôturé")

        file = discord.File(fp=buffer, filename=f"{interaction.channel.name}-transcript.txt")
        await log_channel.send(embed=embed, file=file)

        await interaction.channel.delete()


class RequestView(View):
    def __init__(self, user: discord.User, reason: str):
        super().__init__(timeout=None)
        self.user = user
        self.reason = reason

    @discord.ui.button(label="✅ Accepter", style=discord.ButtonStyle.success, custom_id="accept_ticket")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await create_ticket_channel(interaction.guild, self.user, self.reason)
        await interaction.message.edit(content=f"✅ Demande acceptée par {interaction.user.mention}.", view=None)
        try:
            await self.user.send(f"🎫 Votre demande de ticket pour **{self.reason.replace('_', ' ').title()}** a été acceptée.")
        except:
            pass

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.danger, custom_id="deny_ticket")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.message.edit(content=f"❌ Demande refusée par {interaction.user.mention}.", view=None)
        try:
            await self.user.send("❌ Votre demande de ticket a été refusée par le staff.")
        except:
            pass


class TicketSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Candidature joueur", emoji="🎮", value="candidature_joueur"),
            discord.SelectOption(label="Candidature staff", emoji="🛡️", value="candidature_staff"),
            discord.SelectOption(label="Problème technique", emoji="🛠️", value="probleme_technique"),
            discord.SelectOption(label="Signaler un comportement", emoji="🚨", value="signaler_comportement")
        ]
        super().__init__(placeholder="Choisissez le type de ticket", options=options, custom_id="ticket_reason")

    async def callback(self, interaction: discord.Interaction):
        config = ticket_config.get(interaction.guild.id)
        if not config:
            await interaction.response.send_message("❌ Le système de ticket n'est pas encore configuré.", ephemeral=True)
            return

        request_channel = bot.get_channel(config["request_channel"])
        staff_role = bot.get_guild(interaction.guild.id).get_role(config["staff_role"])

        embed = discord.Embed(
            title="📝 Nouvelle demande de ticket",
            description=f"**Utilisateur :** {interaction.user.mention}\n**Raison :** `{self.values[0].replace('_', ' ').title()}`",
            color=0xffc107,
            timestamp=datetime.utcnow())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Demande en attente d'une décision du staff.")

        view = RequestView(user=interaction.user, reason=self.values[0])
        await request_channel.send(content=staff_role.mention, embed=embed, view=view)

        await interaction.response.send_message("✅ Votre demande a été envoyée au staff. En attente d'une réponse.", ephemeral=True)


class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# === TICKET SETUP ===

@bot.tree.command(name="ticketsetup", description="Configurer le système de ticket")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    staff_role="Rôle du staff pour gérer les tickets",
    ticket_category="Catégorie où seront créés les tickets",
    panel_channel="Salon où afficher le panneau de ticket",
    request_channel="Salon pour recevoir les demandes de ticket",
    log_channel="Salon pour les logs de tickets"
)
async def ticketsetup(interaction: discord.Interaction,
                      staff_role: discord.Role,
                      ticket_category: discord.CategoryChannel,
                      panel_channel: discord.TextChannel,
                      request_channel: discord.TextChannel,
                      log_channel: discord.TextChannel):
    ticket_config[interaction.guild.id] = {
        "staff_role": staff_role.id,
        "category": ticket_category.id,
        "panel_channel": panel_channel.id,
        "request_channel": request_channel.id,
        "log_channel": log_channel.id
    }

    embed = discord.Embed(
        title="🎟️ Centre de Support",
        description="Bienvenue dans le centre d’assistance.\n\nVeuillez sélectionner une option ci-dessous pour ouvrir un ticket.",
        color=0x5865F2)
    embed.set_footer(text="Fusion Support - Réponse rapide assurée")

    await panel_channel.send(embed=embed, view=TicketView())
    await interaction.response.send_message("✅ Panneau de ticket configuré avec succès.", ephemeral=True)

# === CREATE TICKET ===

async def create_ticket_channel(guild, user, reason_key):
    config = ticket_config[guild.id]
    category = bot.get_channel(config["category"])
    staff_role = guild.get_role(config["staff_role"])
    log_channel = bot.get_channel(config["log_channel"])

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    channel_name = f"ticket-{user.name}".lower().replace(" ", "-")
    ticket_channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

    embed = discord.Embed(
        title="🎫 Ticket ouvert",
        description=f"Bonjour {user.mention}, merci d’avoir ouvert un ticket pour **{reason_key.replace('_', ' ').title()}**.\nUn membre du staff va vous répondre sous peu.",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="Appuyez sur le bouton ci-dessous pour fermer le ticket.")

    view = View()
    view.add_item(CloseButton())
    await ticket_channel.send(content=staff_role.mention, embed=embed, view=view)

# === COMMAND: PING ===

@bot.tree.command(name="ping", description="Répond avec Pong! et la latence du bot")
async def ping(interaction: discord.Interaction):
    start = time.perf_counter()
    await interaction.response.defer()
    end = time.perf_counter()
    latency = (end - start) * 1000
    await interaction.followup.send(f"Pong! Latence: {latency:.2f} ms")

@bot.tree.command(name="serverinfo", description="Affiche les informations du serveur")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(
        title=f"Infos du serveur {guild.name}",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="ID", value=guild.id)
    embed.add_field(name="Créé le", value=guild.created_at.strftime("%d/%m/%Y %H:%M"))
    embed.add_field(name="Membres", value=guild.member_count)
    embed.add_field(name="Rôles", value=len(guild.roles))
    embed.add_field(name="Boosts", value=guild.premium_subscription_count)
    embed.set_footer(text=f"ID du serveur : {guild.id}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kick", description="Expulse un membre du serveur")
@app_commands.describe(user="Membre à expulser", reason="Raison de l'expulsion")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "Aucune raison fournie"):
    try:
        await user.kick(reason=reason)
        await interaction.response.send_message(f"✅ {user.mention} a été expulsé.\nRaison : {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Impossible d'expulser {user.mention}.\nErreur : {e}", ephemeral=True)


@bot.tree.command(name="ban", description="Bannit un membre du serveur")
@app_commands.describe(user="Membre à bannir", reason="Raison du bannissement")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "Aucune raison fournie"):
    try:
        await user.ban(reason=reason)
        await interaction.response.send_message(f"✅ {user.mention} a été banni.\nRaison : {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Impossible de bannir {user.mention}.\nErreur : {e}", ephemeral=True)


@bot.tree.command(name="unban", description="Débanni un utilisateur du serveur")
@app_commands.describe(user="Utilisateur à débannir (ID ou tag)")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user: str):
    user_name, user_discriminator = None, None
    if "#" in user:
        user_name, user_discriminator = user.split("#")

    async for ban_entry in interaction.guild.bans():
        banned_user = ban_entry.user
        if (user_name and user_discriminator and banned_user.name == user_name and banned_user.discriminator == user_discriminator) or str(banned_user.id) == user:
            await interaction.guild.unban(banned_user)
            await interaction.response.send_message(f"✅ {banned_user.mention} a été débanni.")
            return

    await interaction.response.send_message(f"❌ Utilisateur non trouvé dans la liste des bannis.", ephemeral=True)



@bot.tree.command(name="clear", description="Supprime un nombre de messages dans le salon")
@app_commands.describe(amount="Nombre de messages à supprimer (max 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("❌ Le nombre doit être entre 1 et 100.", ephemeral=True)
        return

    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 {len(deleted)} messages supprimés.", ephemeral=True)


@bot.tree.command(name="help", description="Affiche la liste des commandes")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Commandes disponibles",
        description=(
            "/kick [user] [reason] - Expulse un membre\n"
            "/ban [user] [reason] - Bannit un membre\n"
            "/unban [user] - Débanni un utilisateur\n"
            "/clear [amount] - Supprime des messages\n"
            "/serverinfo - Affiche les infos du serveur\n"
            "/ping - Teste la latence du bot"
        ),
        color=0x5865F2,
        timestamp=datetime.utcnow()
    )
    await interaction.response.send_message(embed=embed)



@bot.event
async def on_member_join(member):
    embed = discord.Embed(
        title="Bienvenue !",
        description=f"Bienvenue sur le serveur, {member.mention} ! 🎉",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.avatar.url if member.avatar else discord.Embed.Empty)
    embed.set_footer(text="Nouveau membre")

    # Change ici pour le channel où tu veux envoyer le message de bienvenue (par ID)
    channel = bot.get_channel(1379378729305899079)  
    if channel:
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(
        title="Au revoir...",
        description=f"{member.mention} a quitté le serveur. 😢",
        color=discord.Color.red()
    )
    embed.set_thumbnail(url=member.avatar.url if member.avatar else discord.Embed.Empty)
    embed.set_footer(text="Membre parti")

    # Même channel que pour le join, tu peux en mettre un autre si tu veux
    channel = bot.get_channel(1383479357351268372)
    if channel:
        await channel.send(embed=embed)

# On stocke les actions par membre + type d'action : timestamps des actions
role_remove_times = defaultdict(list)
channel_delete_times = defaultdict(list)
ban_times = defaultdict(list)
message_times = defaultdict(list)

# Seuils et durées (réalistes pour protection anti-raid)
ROLE_REMOVE_LIMIT = 6
ROLE_REMOVE_WINDOW = 30  # secondes

CHANNEL_DELETE_LIMIT = 3
CHANNEL_DELETE_WINDOW = 5  # secondes

BAN_LIMIT = 3
BAN_WINDOW = 5  # secondes

MESSAGE_LIMIT = 15
MESSAGE_WINDOW = 7  # secondes

async def ban_user(guild, user_id, reason):
    try:
        member = guild.get_member(user_id)
        if member:
            await member.ban(reason=reason)
            print(f"[ANTI-RAID] Banni {member} pour {reason}")
    except Exception as e:
        print(f"Erreur en ban : {e}")

def clean_old_entries(times_list, window):
    cutoff = datetime.utcnow() - timedelta(seconds=window)
    while times_list and times_list[0] < cutoff:
        times_list.pop(0)

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    entry = None
    async for e in guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
        entry = e
        break
    if entry:
        user = entry.user
        times = role_remove_times[user.id]
        now = datetime.utcnow()
        times.append(now)
        clean_old_entries(times, ROLE_REMOVE_WINDOW)
        if len(times) >= ROLE_REMOVE_LIMIT:
            await ban_user(guild, user.id, "Suppression massive de rôles")

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    entry = None
    async for e in guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
        entry = e
        break
    if entry:
        user = entry.user
        times = channel_delete_times[user.id]
        now = datetime.utcnow()
        times.append(now)
        clean_old_entries(times, CHANNEL_DELETE_WINDOW)
        if len(times) >= CHANNEL_DELETE_LIMIT:
            await ban_user(guild, user.id, "Suppression massive de salons")

@bot.event
async def on_member_ban(guild, user):
    entry = None
    async for e in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
        entry = e
        break
    if entry:
        user_doing_ban = entry.user
        times = ban_times[user_doing_ban.id]
        now = datetime.utcnow()
        times.append(now)
        clean_old_entries(times, BAN_WINDOW)
        if len(times) >= BAN_LIMIT:
            await ban_user(guild, user_doing_ban.id, "Ban multiple rapide")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    times = message_times[user_id]
    now = datetime.utcnow()
    times.append(now)
    clean_old_entries(times, MESSAGE_WINDOW)
    if len(times) >= MESSAGE_LIMIT:
        await ban_user(message.guild, user_id, "Flood de messages")

    await bot.process_commands(message)


# === READY ===

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user}")

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ['DISCORD_TOKEN']  # le token caché dans les secrets Replit (Settings > Secrets)
    bot.run(TOKEN)