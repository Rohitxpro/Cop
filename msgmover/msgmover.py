from redbot.core import Config, commands, checks
from redbot.core.utils.predicates import ReactionPredicate
from redbot.core.utils.menus import start_adding_reactions
from urllib.request import urlopen
import mimetypes
import discord
from discord import Webhook, AsyncWebhookAdapter
import aiohttp
import asyncio
import random
import requests
import json
import base64
from io import BytesIO

class Msgmover(commands.Cog):
    """Move messages around, cross-channels, cross-server!
    
    msgrelay: Forward all of a channel's messages to another channel/server
    msgcopy: Copy a set # of past messages to another channel/server"""

    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=806715409318936616)
        self.bot = bot
        default_guild = {
            "msgrelayStoreV2": {},
            "relayTimer": 20,
        }
        """
            "msgrelayStoreV2": {
                "chanId": [
                    {
                        "toWebhook": str,
                        "pref": bool,
                        "pref": bool,
                    },
                ],
            }
        """
        self.config.register_guild(**default_guild)

    # This cog does not store any End User Data
    async def red_get_data_for_user(self, *, user_id: int):
        return {}
    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:
        pass


    # Utility Commands

    def relayGetData(self, json):
        relayInfo = {
            "toWebhook": json.get("toWebhook", ""),
            "attachsAsUrl": json.get("attachsAsUrl", True),
            "userProfiles": json.get("userProfiles", True),
        }
        return relayInfo

    async def relayAddChannel(self, ctx, chanObj, toWebhook):
        msgrelayStoreV2 = await self.config.guild(ctx.guild).msgrelayStoreV2()
        
        # Set attachsAsUrl
        attachsAsUrl = await ctx.send("Do you want attachments (images) to be forwarded as links?\n> **Yes:** Images will be sent as links\n> **No:** Images will be re-uploaded as a new file")
        start_adding_reactions(attachsAsUrl, ReactionPredicate.YES_OR_NO_EMOJIS)
        attachsAsUrlPred = ReactionPredicate.yes_or_no(attachsAsUrl, ctx.author)
        await ctx.bot.wait_for("reaction_add", check=attachsAsUrlPred)

        # Set userProfiles
        userProfiles = await ctx.send("Do you want messages to be forwarded with profiles?\n> **Yes:** Messages will be forwarded with usernames and profile pics\n> **No:** Messages will use the webhook's name and image instead")
        start_adding_reactions(userProfiles, ReactionPredicate.YES_OR_NO_EMOJIS)
        userProfilesPred = ReactionPredicate.yes_or_no(userProfiles, ctx.author)
        await ctx.bot.wait_for("reaction_add", check=userProfilesPred)

        # Create data store
        try:
            relayInfo = {
                "toWebhook": str(toWebhook),
                "attachsAsUrl": attachsAsUrlPred.result,
                "userProfiles": userProfilesPred.result,
            }
        except:
            return False

        # Append to data
        try:
            msgrelayStoreV2[str(chanObj.id)].append(relayInfo)
        except KeyError:
            msgrelayStoreV2[str(chanObj.id)] = [relayInfo]
        except:
            return False

        # Return changes
        return msgrelayStoreV2

    async def relayRemoveChannel(self, ctx, channel, itemToDelete):
        # Retrieve stored data
        msgrelayStoreV2 = await self.config.guild(ctx.guild).msgrelayStoreV2()

        # Remove from data
        if itemToDelete <= 0:
            msgrelayStoreV2.pop(str(channel.id), None)
        else:
            # Zero-indexed
            msgrelayStoreV2[str(channel.id)].pop(itemToDelete-1)

        # Push changes
        await self.config.guild(ctx.guild).msgrelayStoreV2.set(msgrelayStoreV2)
        return True

    async def relayCheckInput(self, ctx, toChannel):
        # Find/create webhook at destination if input is a channel
        if type(toChannel) == discord.TextChannel:
            toWebhook = await self.webhookFinder(toChannel)
            if toWebhook == False:
                await ctx.send("An error occurred: could not create webook. Am I missing permissions?")
                return False
            return toWebhook
        # Use webhook url as-is if there is https link (doesn't have to be Discord)
        if "https://" in toChannel:
            return str(toChannel)
        # Error likely occurred, return False
        await ctx.send("Invalid webhook URL. Create a webhook for the channel you want to send to. https://support.discord.com/hc/article_attachments/1500000463501/Screen_Shot_2020-12-15_at_4.41.53_PM.png")
        return False

    async def timestampEmbed(self, ctx, utcTimeObj):
        embedColor = await ctx.embed_colour()
        embed = discord.Embed(color=embedColor, timestamp=utcTimeObj)
        embed.set_footer(text='\u200b')
        return embed

    async def webhookFinder(self, channel):
        # Find a webhook that the bot made
        try:
            whooklist = await channel.webhooks()
        except:
            return False
        # Return if match
        for wh in whooklist:
            if self.bot.user == wh.user:
                return wh.url
        # If the function got here, it means there isn't one that the bot made
        try:
            newHook = await channel.create_webhook(name="Webhook")
            return newHook.url
        # Could not create webhook, return False
        except:
            return False


    # Bot Commands

    @commands.group()
    @checks.guildowner_or_permissions(manage_messages=True)
    async def msgmover(self, ctx: commands.Context):
        """Hi! Thanks for installing msgmover!

        Msgmover comes with two key features, both of which use webhooks to move messages from one place to another with a close-to-native feel:

        **`[p]msgcopy`** - Copies messages from one channel to another
        **`[p]msgrelay`** - Forward messages to other channels/servers

        To get started:

        **`[p]msgcopy`** can be used by users with **Manage Messages** permissions.
        **`[p]msgrelay`** can only be used by server admins with **Administrator** permissions.

        Need help? [Reach us in our Support Discord >](https://coffeebank.github.io/discord)
        """
        if not ctx.invoked_subcommand:
            pass

    @commands.command(aliases=["msgmove"])
    @checks.guildowner_or_permissions(manage_messages=True)
    async def msgcopy(self, ctx, fromChannel: discord.TextChannel, toChannel: discord.TextChannel, maxMessages:int, skipMessages:int=0):
        """Copies messages from one channel to another
        
        Retrieve 'maxMessages' number of messages from history, and optionally discard 'skipMessages' number of messages from the retrieved list.
        
        Retrieving more than 10 messages will result in Discord ratelimit throttling, so please be patient.
        
        Requires webhook permissions."""
        await ctx.message.add_reaction("⏳")

        toWebhook = await self.webhookFinder(toChannel)
        if toWebhook == False:
            return await ctx.send("Error trying to create webhook at destination channel.")

        if skipMessages >= maxMessages:
            return await ctx.send("Cannot skip more messages than the max number of messages you are retrieving.")

        # Start webhook session
        async with aiohttp.ClientSession() as session:
            webhook = Webhook.from_url(toWebhook, adapter=AsyncWebhookAdapter(session))

            # Retrieve messages, sorted by oldest first
            msgList = await fromChannel.history(limit=maxMessages).flatten()
            msgList.reverse()
            if skipMessages > 0:
                # https://stackoverflow.com/a/37105499
                msgList = msgList[:-skipMessages or None]

            # Send them via webhook
            msgItemLast = msgList[0].created_at
            for msgItem in msgList:
                # Send timestamp if it's been more than 10mins time difference
                # If they equal, it means it's the first item, so send timestamp
                if msgItemLast == msgItem.created_at or (msgItem.created_at-msgItemLast).total_seconds() > 600:
                    await webhook.send(
                        username="\u17b5\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u17b5",
                        avatar_url='https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/0-Background.svg/300px-0-Background.svg.png',
                        embed=await self.timestampEmbed(ctx, msgItem.created_at)
                    )
                configJson = self.relayGetData({"attachsAsUrl": False, "userProfiles": True})
                try:
                    status = await self.msgFormatter(webhook, msgItem, configJson)
                    if status is not True:
                        await ctx.send("Failed to send: "+str(msgItem))
                except:
                    await ctx.send("Failed to send: "+str(msgItem))
                # Save timestamp to msgItemLast
                msgItemLast = msgItem.created_at

        # Add react on complete
        await ctx.message.add_reaction("✅")

    @commands.group()
    @checks.guildowner_or_permissions(administrator=True)
    async def msgrelay(self, ctx: commands.Context):
        """Set message relays

        Message relays allow you to forward messages to another server via a webhook.

        *v2 released with breaking changes on 29 Jun 2021.*
        *Old data saved under `v1` command.*
        *[Join the Support Discord for announcements and more info](https://coffeebank.github.io/discord)*"""
        if not ctx.invoked_subcommand:
            # Message Relays
            msgrelayStoreV2 = await self.config.guild(ctx.guild).msgrelayStoreV2()
            relayList = ""
            for relayId in msgrelayStoreV2:
                relayList += f"**<#{relayId}>**\n{str(msgrelayStoreV2[relayId])}\n\n"
            eg = discord.Embed(color=(await ctx.embed_colour()), title="Message Relays in this Server", description=relayList)
            await ctx.send(embed=eg)
            # Relay settings
            es = discord.Embed(color=(await ctx.embed_colour()), title="Message Relay Settings in this Server")
            es.add_field(name="Relay Timer", value=await self.config.guild(ctx.guild).relayTimer(), inline=True)
            await ctx.send(embed=es)

    @msgrelay.command(name="add")
    async def mmmradd(self, ctx, fromChannel: discord.TextChannel, toChannel):
        """Create a message relay
        
        Currently only supports webhook urls. [How to create webhooks.](https://support.discord.com/hc/article_attachments/1500000463501/Screen_Shot_2020-12-15_at_4.41.53_PM.png)
        *[Help us develop support for #channels >](https://coffeebank.github.io/discord)*"""

        # Error catching
        relayCheckInput = await self.relayCheckInput(ctx, toChannel)
        if relayCheckInput == False:
            return

        # Create entry
        relayAdd = await self.relayAddChannel(ctx, fromChannel, relayCheckInput)
        if relayAdd == False:
            return await ctx.send("Setup was stopped. Exited.")
        else:
            await self.config.guild(ctx.guild).msgrelayStoreV2.set(relayAdd)

        # Test
        try:
            await fromChannel.send("**Channels are now linked!**\nThis is a sample message.")
        except:
            return await ctx.send("Setup was successfully completed, but some permissions may be missing.")
        await ctx.message.add_reaction("✅")

    @msgrelay.command(name="edit")
    async def mmmredit(self, ctx, fromChannel: discord.TextChannel, itemToEdit: int, toChannel):
        """Edit a message relay
        
        Currently only supports webhook urls. [How to create webhooks.](https://support.discord.com/hc/article_attachments/1500000463501/Screen_Shot_2020-12-15_at_4.41.53_PM.png)
        *[Help us develop support for #channels >](https://coffeebank.github.io/discord)*"""
        # Error catching
        relayCheckInput = await self.relayCheckInput(ctx, toChannel)
        if relayCheckInput == False:
            return

        # Ask for input and have it successfully complete before deleting old entry
        relayAdd = await self.relayAddChannel(ctx, fromChannel, relayCheckInput)
        if relayAdd == False:
            return await ctx.send("Setup was stopped. Exited.")
        else:
            # Create new entry
            await self.config.guild(ctx.guild).msgrelayStoreV2.set(relayAdd)
            # Delete old entry
            await self.relayRemoveChannel(ctx, fromChannel, itemToEdit)

        # Test
        try:
            await fromChannel.send("**Channels are now linked!**\nThis is a sample message.")
        except:
            return await ctx.send("Setup was successfully completed, but some permissions may be missing.")
        await ctx.message.add_reaction("✅")

    @msgrelay.command(name="delete", aliases=["remove"])
    async def mmmrdelete(self, ctx, fromChannel: discord.TextChannel, itemToDelete: int):
        """Delete a message relay
        
        fromChannel: the originating #channel
        itemToDelete: put 1, 2, ... for which one you want to delete.
        
        To delete all relays for a fromChannel, set itemToDelete to 0 (zero)."""
        result = await self.relayRemoveChannel(ctx, fromChannel, itemToDelete)
        if result == False:
            return await ctx.send("Deletion failed. Please report this error to the support server at <https://coffeebank.github.io/discord>.")
        await ctx.message.add_reaction("✅")

    @msgrelay.command(name="settimer")
    async def mmmrsettimer(self, ctx, seconds: int):
        """Seconds after the relay checks for edited/deleted messages
        
        To disable checking for edits/deleted messages after sending, set seconds to 0 (zero)."""
        await self.config.guild(ctx.guild).relayTimer.set(seconds)
        await ctx.message.add_reaction("✅")



    # Listeners

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore message if it's a webhook
        # REQUIRED IF TWO-WAY CHAT REDIRECTS
        # TO STOP A TWO-WAY REDIRECT, USE [p]msgrelay delete #channel
        if message.webhook_id:
            return
        # only do anything if message is sent in a guild
        if message.guild:
            relayStore = await self.config.guild(message.guild).msgrelayStoreV2()
            # Retrieve webhook info from channel store
            if str(message.channel.id) in relayStore:
                hookData = relayStore[str(message.channel.id)]
                relayTimer = await self.config.guild(message.guild).relayTimer()
                # Migrate data to multi-hook support if needed
                try:
                    assert isinstance(hookData, list)
                except AssertionError:
                    hookData = await self.fixMsgrelayStoreV2alpha(message)
                # Send along webhook for each in array
                for wh in hookData:
                    configJson = self.relayGetData(wh)
                    async with aiohttp.ClientSession() as session:
                        webhook = Webhook.from_url(wh["toWebhook"], adapter=AsyncWebhookAdapter(session))
                        whResult = await self.msgFormatter(webhook, message, configJson)
                        wh["whResult"] = whResult.id
                # Wait, then check for edits/deletes
                if relayTimer <= 0:
                    return
                else:
                    await asyncio.sleep(relayTimer)
                    try:
                        endMsg = await message.channel.fetch_message(message.id)
                    except discord.errors.NotFound:
                        for wf in hookData:
                            configJson = self.relayGetData(wh)
                            async with aiohttp.ClientSession() as session:
                                webhook = Webhook.from_url(wf["toWebhook"], adapter=AsyncWebhookAdapter(session))
                                await self.msgFormatter(webhook, message, configJson, deleteMsgId=wf.get("whResult", None))
                    else:
                        if endMsg.edited_at:
                            for wf in hookData:
                                configJson = self.relayGetData(wh)
                                async with aiohttp.ClientSession() as session:
                                    webhook = Webhook.from_url(wf["toWebhook"], adapter=AsyncWebhookAdapter(session))
                                    await self.msgFormatter(webhook, endMsg, configJson, editMsgId=wf.get("whResult", None))
            else:
                return
        else:
            return

    async def msgFormatter(self, webhook, message, json, editMsgId=None, deleteMsgId=None):
        # webhook: A webhook object from discord.py
        # message: A message object from discord.py
        # json: A {dict} with config variables

        # Delete the message if it's delete
        if deleteMsgId is not None:
            try:
                return await webhook.delete_message(deleteMsgId)
            except:
                return False

        # Edit the message if it's edit
        if editMsgId is not None:
            try:
                return await webhook.edit_message(
                    message_id=editMsgId,
                    content=message.clean_content
                )
            except discord.HTTPException:
                return await webhook.edit_message(
                    message_id=editMsgId,
                    content="**Discord:** Unsupported content\n"+str(message.clean_content)
                )
            except:
                print("failed at webhook")
                return False

        # Check for system messages, Set up user profile
        userProfilesName = None
        userProfilesAvatar = None
        if message.type == discord.MessageType.default:
            msgContent = message.clean_content
            if json["userProfiles"] == True:
                userProfilesName = message.author.display_name
                userProfilesAvatar = message.author.avatar_url
        else:
            msgContent = "**Discord:** "+str(message.type)
            if json["userProfiles"] == True:
                userProfilesName = "\u17b5\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u2002\u17b5"
                userProfilesAvatar = 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/0-Background.svg/300px-0-Background.svg.png'

        # Add reply if exists
        if message.reference and message.type == discord.MessageType.default:
            # Retrieve replied-to message
            refObj = message.reference.resolved
            replyEmbed = discord.Embed(color=discord.Color(value=0x25c059), description="")
            # Check whether message is empty
            if refObj.clean_content:
                replyBody = (refObj.clean_content[:56] + '...') if len(refObj.clean_content) > 56 else refObj.clean_content
            else:
                replyBody = "Click to see attachment 🖼️"
            # Create link to message
            replyTitle = f"↪️ {replyBody}"
            if json["userProfiles"] == True:
                replyEmbed.set_author(name=replyTitle, icon_url=refObj.author.avatar_url, url=refObj.jump_url)
            else:
                replyEmbed.set_author(name=replyTitle, url=refObj.jump_url)
            # Send this before the original message so that the embed appears above the message in chat
            await webhook.send(
                username=userProfilesName,
                avatar_url=userProfilesAvatar,
                embed=replyEmbed
            )

        # Add embed if exists
        msgEmbed = None
        # Do not set the embed if it came from a http link in the message (fixes repo issue #4)
        if message.embeds and "http" not in msgContent:
            msgEmbed = message.embeds

        # Add attachment if exists
        msgAttach = None
        if message.attachments:
            attachSuccess = False
            if json["attachsAsUrl"] == False:
                try:
                    # 8MB upload limit
                    totalSize = 0
                    for mm in message.attachments:
                        totalSize += mm.size
                    assert totalSize < 8000000
                except AssertionError:
                    # See if each file is under 8MB, maybe we can send individually
                    for mm in message.attachments:
                        try:
                            assert mm.size < 8000000
                            await webhook.send(
                                username=userProfilesName,
                                avatar_url=userProfilesAvatar,
                                files=[await mm.to_file()],
                                wait=True
                            )
                        except AssertionError:
                            await webhook.send(
                                "**Discord:** File too large\n"+str(mm.url),
                                username=userProfilesName,
                                avatar_url=userProfilesAvatar,
                                wait=True
                            )
                    attachSuccess = True
                else:
                    msgAttach = [await msgA.to_file() for msgA in message.attachments]
                    attachSuccess = True
            # Fallback if uploads don't work
            if json["attachsAsUrl"] == True or attachSuccess == False:
                for msgB in message.attachments:
                    msgContent += "\n"+str(msgB.url)

        # Add activity if exists
        if message.activity:
            msgContent += f"\n**Discord:** Activity\n"+str(message.activity)
        if message.application:
            msgContent += f"\n**Discord:** {message.application.name}\n{message.application.description}"

        # Add sticker if exists
        if message.stickers:
            for msgSticker in message.stickers:
                msgStickerItem = await msgSticker.image_url_as(size=128)
                if msgStickerItem is not None:
                    msgContent += "\n"+str(msgStickerItem)
                else:
                    msgContent += "\n**Discord:** Sticker\n"+str(msgSticker.name)+", "+str(msgSticker.pack_id)

        # Send core message
        whMsg = False
        try:
            whMsg = await webhook.send(
                msgContent,
                username=userProfilesName,
                avatar_url=userProfilesAvatar,
                embeds=msgEmbed,
                files=msgAttach,
                wait=True
            )
        except discord.HTTPException:
            # catch HTTPException: 400 Bad Request (error code: 50006): Cannot send an empty message
            whMsg = await webhook.send(
                "**Discord:** Unsupported content\n"+str(msgContent),
                username=userProfilesName,
                avatar_url=userProfilesAvatar,
                embeds=msgEmbed,
                files=msgAttach,
                wait=True
            )
        except:
            pass
        
        # Need to tell endpoint that function ended, so that sent message order is enforceable by await
        return whMsg


    # Legacy Commands

    async def fixMsgrelayStoreV2alpha(self, ctx):
        oldData = await self.config.guild(ctx.guild).msgrelayStoreV2()
        if isinstance(oldData[str(ctx.channel.id)], list) == False:
            newData = [oldData[str(ctx.channel.id)]]
            oldData[str(ctx.channel.id)] = newData
            await self.config.guild(ctx.guild).msgrelayStoreV2.set(oldData)
            return newData
        else:
            return oldData[str(ctx.channel.id)]

    @msgrelay.group(name="v1")
    @checks.is_owner()
    async def msgrelayV1(self, ctx: commands.Context):
        """View legacy data

        Settings will not be modifiable, and it is encouraged to migrate to v2.

        The new v2 shifts data from being under the Bot Owner to separate guilds, and allows guild owners to create their own relays.
        
        Because of this change, the old settings are incompatible with the new settings."""
        if not ctx.invoked_subcommand:
            msgrelayStore = await self.config.msgrelayStore()
            relayList = ""
            for relayId in msgrelayStore:
                relayList += f"**<#{relayId}>**\n{msgrelayStore[relayId]}\n\n"
            eg = discord.Embed(color=(await ctx.embed_colour()), title="Legacy Relays (no longer work)", description=relayList)
            await ctx.send(embed=eg)
    @msgrelayV1.command(name="reset")
    async def mmmrV1reset(self, ctx, areYouSure: bool):
        """⚠️ Deletes all V1 relays
        
        Type **`[p]msgrelay reset True`** if you're absolutely sure."""
        if areYouSure == True:
            await self.config.msgrelayChannels.set([])
            await self.config.msgrelayStore.set({})
            await ctx.message.add_reaction("✅")
