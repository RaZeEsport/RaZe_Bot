import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, Button
import datetime
import io
import os

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
            timestamp=datetime.datetime.utcnow()
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
            description=f"**Utilisateur :** {interaction.user.mention}\n"
                        f"**Raison :** `{self.values[0].replace('_', ' ').title()}`",
            color=0xffc107,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Demande en attente d'une décision du staff.")

        view = RequestView(user=interaction.user, reason=self.values[0])
        await request_channel.send(content=staff_role.mention, embed=embed, view=view)

        await interaction.response.send_message(
            "✅ Votre demande a été envoyée au staff. En attente d'une réponse.",
            ephemeral=True
        )


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
async def ticketsetup(
    interaction: discord.Interaction,
    staff_role: discord.Role,
    ticket_category: discord.CategoryChannel,
    panel_channel: discord.TextChannel,
    request_channel: discord.TextChannel,
    log_channel: discord.TextChannel
):
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
        color=0x5865F2
    )
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
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text="Appuyez sur le bouton ci-dessous pour fermer le ticket.")

    view = View()
    view.add_item(CloseButton())
    await ticket_channel.send(content=staff_role.mention, embed=embed, view=view)


# === READY ===

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot connecté : {bot.user.name}")

# === RUN ===
TOKEN = os.getenv('DISCORD_TOKEN')

bot.run(TOKEN)