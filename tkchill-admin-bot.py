import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import asyncio
import datetime
import os
import json  # THÊM THƯ VIỆN JSON ĐỂ LƯU SỐ TICKET
from aiohttp import web
import aiohttp
import motor.motor_asyncio
from pymongo import ReturnDocument

# --- CẤU HÌNH (BẠ sN CẦN ĐIỀN ĐÚNG ID VÀO ĐÂY) ---
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = 1365693391668777051
ADMIN_CHANNEL_ID = 1448258683627638895
BAN_ROLE_ID = 1408787259322273913
VOTE_CHANNEL_ID = 1456467745909637240
MEMBER_ROLE_ID = 1375110178868826142
OWNER_ID = 856704693215166474
MARKETPLACE_CHANNEL_ID = 1461357458252365984

# KÊNH THÔNG BÁO XỬ PHẠT MỚI
ANNOUNCEMENT_CHANNEL_ID = 1511395838264610897 # Thay bằng ID của kênh bot-announcements

# --- CẤU HÌNH TICKET ---
TICKET_CATEGORY_ID = 1511235041781350511 
ROLE_ADMIN_ID = 1365960976016347136 
ROLE_DEV_ID = 1366433221687906304   
ROLE_STAFF_ID = 1493908725231128617 

# --- CẤU HÌNH VOTE ---
VOTE_DURATION = 900  # 15 phút
MIN_VOTES_REQUIRED = 4
ALLOWED_ROLES = ["Admin", "DEV", "STAFF"]

# --- KẾT NỐI MONGODB ATLAS ---
# Tận dụng luôn cái Database của con Bot 1
MONGO_URI = os.environ.get("MONGO_URI")
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = db_client["tkchill_database"] 
ticket_collection = db["ticket_counter"]
punishment_collection = db["punishment_logs"]

# --- HÀM TỰ ĐỘNG ĐÁNH SỐ TICKET (ĐÃ NÂNG CẤP LÊN MONGODB) ---
async def get_next_ticket_number() -> str:
    try:
        # Lệnh $inc giúp tự động cộng 1 cực kỳ an toàn
        # Đảm bảo không bao giờ bị trùng số dù có 10 người mở ticket cùng lúc
        doc = await ticket_collection.find_one_and_update(
            {"_id": "master_ticket"},
            {"$inc": {"counter": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        counter = doc.get("counter", 1)
        return f"{counter:03d}"
    except Exception as e:
        print(f"❌ Lỗi lấy số Ticket từ MongoDB: {e}")
        return "999" # Số dự phòng chống sập bot nếu rớt mạng

# Thiết lập Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# === WEB SERVER ĐỂ NHẬN PING ===
async def handle_ping(request):
    return web.Response(text="Bot 2 is alive!")

app = web.Application()
app.add_routes([web.get('/', handle_ping)])

async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f">> Web server đã chạy trên port {port}")

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        self.tree.on_error = self.on_app_command_error
        self.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))

        self.add_view(TicketPanelView())
        print(">> Đã đồng bộ tất cả lệnh Slash Commands!")
        
        bot.loop.create_task(start_web_server())
        check_punishments.start()
        self.ping_bot1.start()

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingAnyRole):
            await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)
        else:
            print(f"Lỗi: {error}")

    @tasks.loop(minutes=2.0)
    async def ping_bot1(self):
        bot1_url = os.environ.get("BOT1_URL")
        if bot1_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(bot1_url) as response:
                        print(f"[Ping Chéo] Đã chọc Bot 1, Status: {response.status}")
            except Exception as e:
                print(f"[Ping Chéo] Lỗi chọc Bot 1: {e}")
        else:
            print("⚠️ Chưa cài BOT1_URL, tính năng Ping chéo đang tắt.")

    @ping_bot1.before_loop
    async def before_ping(self):
        await self.wait_until_ready()

bot = MyBot()

def has_permission(interaction: discord.Interaction) -> bool:
    user_role_names = [role.name for role in interaction.user.roles]
    return any(role_name in user_role_names for role_name in ALLOWED_ROLES)

# === HÀM GỬI THÔNG BÁO XỬ PHẠT (ĐÃ CẬP NHẬT TRẢ VỀ TIN NHẮN & HIỂN THỊ GIỜ HẾT HẠN) ===
async def send_punishment_log(guild: discord.Guild, target: discord.Member, action: str, reason: str, duration: str = None, duration_minutes: int = None):
    channel = guild.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel:
        channel = discord.utils.get(guild.text_channels, name="bot-announcements")

    if channel:
        embed = discord.Embed(
            title="🚨 THÔNG BÁO XỬ PHẠT",
            description=f"Một thành viên vừa bị xử lý vì vi phạm quy định.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Thành viên", value=target.mention, inline=True)
        embed.add_field(name="Hình thức", value=action, inline=True)
        
        if duration:
            # Nếu có thời gian phạt, sử dụng tag hiển thị giờ/đếm ngược của Discord
            if duration_minutes:
                end_timestamp = int(datetime.datetime.now().timestamp() + (duration_minutes * 60))
                time_display = f"{duration}\n**Hết hạn:** <t:{end_timestamp}:t> (<t:{end_timestamp}:R>)"
            else:
                time_display = duration
            embed.add_field(name="Thời gian", value=time_display, inline=True)
            
        safe_reason = reason if (reason and len(reason.strip()) > 0) else "Không có lý do"
        if len(safe_reason) > 1024:
            safe_reason = safe_reason[:1021] + "..."
            
        embed.add_field(name="Lý do", value=safe_reason, inline=False)
        embed.set_thumbnail(url=target.avatar.url if target.avatar else None)
        
        # Lưu tin nhắn vào biến msg và trả về để dùng cho task sửa/xoá sau này
        msg = await channel.send(content=f"📢 {target.mention} đã bị xử phạt!", embed=embed)
        return msg
    return None

# === HỆ THỐNG KIỂM TRA ÁN PHẠT TỰ ĐỘNG BẰNG MONGODB ===
@tasks.loop(minutes=1.0)
async def check_punishments():
    now = datetime.datetime.now().timestamp()
    
    cursor = punishment_collection.find({"status": "active", "expire_at": {"$lte": now}})
    async for doc in cursor:
        target_id = doc['target_id']
        action_type = doc.get('action_type', 'timeout')
        
        # 1. XỬ LÝ HẾT HẠN PHẠT "BAN_TIME"
        if action_type == "soft_ban":
            try:
                guild = bot.get_guild(GUILD_ID)
                if not guild:
                    guild = await bot.fetch_guild(GUILD_ID)

                if guild:
                    # Dùng fetch_member để chống lỗi không tìm thấy người dùng khi Render vừa restart
                    try:
                        target_member = guild.get_member(target_id) or await guild.fetch_member(target_id)
                    except discord.NotFound:
                        target_member = None # User đã tự thoát khỏi server
                        print(f"[Log] User {target_id} đã rời server, không thể gỡ role ban.")

                    if target_member:
                        ban_role = guild.get_role(BAN_ROLE_ID)
                        
                        # CHỈ gỡ role Ban, KHÔNG cấp lại role Member
                        if ban_role and ban_role in target_member.roles:
                            await target_member.remove_roles(ban_role, reason="Hết hạn ban tạm thời (Chưa cấp lại Role)")
                            
                            # Nhắn tin (DM) nhắc họ đi xin lại role
                            try:
                                await target_member.send(
                                    f"✅ Án phạt ban tạm thời của bạn tại server **{guild.name}** đã hết hạn.\n"
                                    f"⚠️ **LƯU Ý QUAN TRỌNG:** Bot không tự động cấp lại quyền thành viên. Vui lòng mở Ticket hỗ trợ hoặc liên hệ Admin/Staff để xin lại Role Member nhé!"
                                )
                            except discord.Forbidden:
                                # Bỏ qua nếu người dùng khóa tính năng nhận tin nhắn từ người lạ (DM)
                                pass
            except Exception as e:
                print(f"Lỗi xử lý gỡ ban cho {target_id}: {e}")

        # 2. SỬA TIN NHẮN LOG TRONG KÊNH THÔNG BÁO
        try:
            channel = bot.get_channel(doc["channel_id"]) or await bot.fetch_channel(doc["channel_id"])
            msg = await channel.fetch_message(doc["message_id"])
            
            embed = msg.embeds[0]
            embed.title = "✅ ĐÃ HOÀN THÀNH CHẤP ÁN"
            
            if action_type == "soft_ban":
                embed.description = f"<@{target_id}> đã hết thời gian xử phạt. Yêu cầu tự liên hệ Admin để xin lại Role."
            else:
                embed.description = f"<@{target_id}> đã hết thời gian xử phạt."
                
            embed.color = discord.Color.green()
            
            await msg.edit(content=f"✅ <@{target_id}> đã hoàn thành án phạt!", embed=embed)
        except Exception:
            pass 
        
        # Cập nhật DB trạng thái hoàn thành
        await punishment_collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "completed", "delete_at": now + (30 * 60)}}
        )
        
    # 3. XÓA TIN NHẮN RÁC (Sau khi hết hạn được 30 phút)
    cursor_del = punishment_collection.find({"status": "completed", "delete_at": {"$lte": now}})
    async for doc in cursor_del:
        try:
            channel = bot.get_channel(doc["channel_id"]) or await bot.fetch_channel(doc["channel_id"])
            msg = await channel.fetch_message(doc["message_id"])
            await msg.delete()
        except Exception:
            pass
        await punishment_collection.delete_one({"_id": doc["_id"]})

@check_punishments.before_loop
async def before_check_punishments():
    await bot.wait_until_ready()

# ==============================================================================
#                        HỆ THỐNG VOTE KICK (TẤT CẢ ĐỀU THẤY)
# ==============================================================================
class PublicVoteView(discord.ui.View):
    def __init__(self, target: discord.Member, action: str, reason: str, duration: int, requester_id: int):
        super().__init__(timeout=None)
        self.target, self.action, self.reason, self.duration = target, action, reason, duration
        self.requester_id = requester_id
        self.agree_voters, self.disagree_voters = set(), set()
        self.is_active = True
        self.message = None

    @discord.ui.button(label="Đồng ý (0)", style=discord.ButtonStyle.green, emoji="👍")
    async def agree_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_active: return await interaction.response.send_message("Đã kết thúc.", ephemeral=True)
        if interaction.user.id in self.disagree_voters: self.disagree_voters.remove(interaction.user.id)
        self.agree_voters.add(interaction.user.id)
        await self.update_buttons(interaction)

    @discord.ui.button(label="Không đồng ý (0)", style=discord.ButtonStyle.red, emoji="👎")
    async def disagree_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_active: return await interaction.response.send_message("Đã kết thúc.", ephemeral=True)
        if interaction.user.id in self.agree_voters: self.agree_voters.remove(interaction.user.id)
        self.disagree_voters.add(interaction.user.id)
        await self.update_buttons(interaction)

    @discord.ui.button(label="Kết thúc ngay", style=discord.ButtonStyle.gray, emoji="🛑", row=1)
    async def end_early_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_active: return await interaction.response.send_message("Cuộc vote đã kết thúc rồi.", ephemeral=True)
        if not (has_permission(interaction) or interaction.user.id == self.requester_id):
            return await interaction.response.send_message("❌ Chỉ Admin/STAFF hoặc Người tạo vote mới được kết thúc!", ephemeral=True)
        await interaction.response.send_message("⚠️ Đã yêu cầu kết thúc sớm!", ephemeral=True)
        await self.finish_vote(interaction.channel)

    async def update_buttons(self, interaction: discord.Interaction):
        self.children[0].label = f"Đồng ý ({len(self.agree_voters)})"
        self.children[1].label = f"Không đồng ý ({len(self.disagree_voters)})"
        await interaction.response.edit_message(view=self)

    async def finish_vote(self, channel):
        if not self.is_active: return
        self.is_active = False
        self.stop()
        agrees, disagrees = len(self.agree_voters), len(self.disagree_voters)
        total = agrees + disagrees
        res_embed = discord.Embed(title="🔔 KẾT QUẢ BỎ PHIẾU", timestamp=datetime.datetime.now())

        if total < MIN_VOTES_REQUIRED:
            res_embed.color = discord.Color.greyple()
            res_embed.description = f"❌ **HỦY BỎ.** Quá ít người quan tâm ({total}/{MIN_VOTES_REQUIRED} phiếu)."
        elif agrees > disagrees:
            res_embed.color = discord.Color.red()
            res_embed.description = f"✅ **THÔNG QUA!**\n👍 Đồng ý: {agrees}\n👎 Phản đối: {disagrees}"
            try:
                guild = channel.guild
                audit_reason = f"Vote: {self.reason}"[:500]
                
                if self.action == "KICK":
                    await self.target.kick(reason=audit_reason)
                    await channel.send(f"👋 Đã Kick {self.target.mention}.")
                    await send_punishment_log(guild, self.target, "Kick (Vote)", audit_reason)
                elif self.action == "BAN":
                    await self.target.ban(reason=audit_reason)
                    await channel.send(f"🚨 Đã Ban {self.target.mention}.")
                    await send_punishment_log(guild, self.target, "Ban (Vote)", audit_reason)
                elif self.action == "TIMEOUT":
                    await self.target.timeout(datetime.timedelta(minutes=self.duration), reason=audit_reason)
                    await channel.send(f"😶 Đã Timeout {self.target.mention} trong {self.duration} phút.")
                    
                    # Gửi log
                    msg = await send_punishment_log(guild, self.target, "Timeout (Vote)", audit_reason, f"{self.duration} phút", duration_minutes=self.duration)
                    
                    # Lưu MongoDB
                    if msg:
                        expire_time = datetime.datetime.now().timestamp() + (self.duration * 60)
                        await punishment_collection.insert_one({
                            "message_id": msg.id,
                            "channel_id": msg.channel.id,
                            "target_id": self.target.id,
                            "expire_at": expire_time,
                            "action_type": "timeout", # Đánh dấu loại phạt
                            "status": "active"
                        })
            except Exception as e:
                await channel.send(f"⚠️ Lỗi thực thi: {e}")
        else:
            res_embed.color = discord.Color.green()
            res_embed.description = f"🛡️ **GIỮ LẠI.** ({'Hòa phiếu' if agrees == disagrees else 'Phản đối thắng'}).\n👍 Đồng ý: {agrees}\n👎 Phản đối: {disagrees}"

        if self.message:
            try: await self.message.edit(view=None, embed=res_embed)
            except: pass

class TicketControlView(discord.ui.View):
    def __init__(self, creator: discord.Member):
        super().__init__(timeout=None)
        self.creator = creator

    @discord.ui.button(label="Vấn đề đã giải quyết", style=discord.ButtonStyle.green, emoji="✅", custom_id="ticket_resolved")
    async def resolve_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction) and interaction.user.id != self.creator.id:
            return await interaction.response.send_message("❌ Bạn không có quyền đóng ticket này!", ephemeral=True)
            
        await interaction.response.send_message("🔄 Đang xử lý đóng ticket...", ephemeral=True)
        
        # --- GỬI LOG VÀO KÊNH ADMIN KHI ĐÓNG TICKET ---
        admin_channel = interaction.guild.get_channel(ADMIN_CHANNEL_ID)
        if admin_channel:
            log_embed = discord.Embed(
                title="🔒 TICKET ĐÃ GIẢI QUYẾT",
                description=f"📌 **Tên phòng:** `{interaction.channel.name}`\n👤 **Người tạo:** {self.creator.mention} (`{self.creator.name}`)\n🔒 **Người đóng:** {interaction.user.mention} (`{interaction.user.name}`)",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now()
            )
            await admin_channel.send(embed=log_embed)

        try:
            await self.creator.send(f"✅ Ticket hỗ trợ của bạn tại server **{interaction.guild.name}** đã được đánh dấu là **Đã Giải Quyết** và đóng lại bởi {interaction.user.name}.")
        except discord.Forbidden:
            pass
            
        await interaction.channel.delete(reason="Ticket đã được giải quyết.")

    @discord.ui.button(label="Hủy Ticket", style=discord.ButtonStyle.red, emoji="🗑️", custom_id="ticket_cancel")
    async def cancel_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction) and interaction.user.id != self.creator.id:
            return await interaction.response.send_message("❌ Bạn không có quyền hủy ticket này!", ephemeral=True)

        await interaction.response.send_message("🔄 Đang hủy ticket...", ephemeral=True)
        
        # --- GỬI LOG VÀO KÊNH ADMIN KHI HỦY TICKET ---
        admin_channel = interaction.guild.get_channel(ADMIN_CHANNEL_ID)
        if admin_channel:
            log_embed = discord.Embed(
                title="❌ TICKET BỊ HỦY",
                description=f"📌 **Tên phòng:** `{interaction.channel.name}`\n👤 **Người tạo:** {self.creator.mention} (`{self.creator.name}`)\n❌ **Người hủy:** {interaction.user.mention} (`{interaction.user.name}`)",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now()
            )
            await admin_channel.send(embed=log_embed)

        try:
            await self.creator.send(f"❌ Ticket của bạn tại server **{interaction.guild.name}** đã bị **Hủy/Từ chối** bởi {interaction.user.name}.")
        except discord.Forbidden:
            pass

        await interaction.channel.delete(reason="Ticket bị hủy.")

# ==============================================================================
# HỆ THỐNG TICKET HỖ TRỢ (ĐÃ NÂNG CẤP SELECT MENU & MODAL)
# ==============================================================================

# Đưa hàm này ra ngoài làm hàm tự do để dễ dàng tái sử dụng cho Modal và Select
async def create_ticket_channel(interaction: discord.Interaction, ticket_type: str, custom_reason: str = None, reported_user_id: str = None):
    guild = interaction.guild
    category = guild.get_channel(TICKET_CATEGORY_ID)
    
    if not category:
        return await interaction.followup.send("❌ Lỗi hệ thống: Không tìm thấy danh mục chứa Ticket. Báo Dev ngay!", ephemeral=True)

    admin_role = guild.get_role(ROLE_ADMIN_ID)
    dev_role = guild.get_role(ROLE_DEV_ID)
    staff_role = guild.get_role(ROLE_STAFF_ID)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False), 
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True), 
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True) 
    }

    for role in [admin_role, dev_role, staff_role]:
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    # ĐÁNH SỐ TỰ ĐỘNG
    ticket_num = await get_next_ticket_number()
    channel_name = f"{interaction.user.name}-ticket-{ticket_num}"
    
    ticket_channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"Tạo ticket loại: {ticket_type} bởi {interaction.user.name}"
    )

    # --- GỬI LOG VÀO KÊNH ADMIN KHI TẠO TICKET MỚI ---
    admin_channel = guild.get_channel(ADMIN_CHANNEL_ID)
    if admin_channel:
        log_embed = discord.Embed(
            title="📩 TICKET MỚI ĐƯỢC TẠO",
            description=f"📌 **Phòng:** {ticket_channel.mention} (`#{channel_name}`)\n👤 **Người tạo:** {interaction.user.mention} (`{interaction.user.name}`)\n📂 **Loại hỗ trợ:** {ticket_type}",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        if reported_user_id:
            log_embed.add_field(name="🚨 Đối tượng bị tố cáo", value=f"<@{reported_user_id}> (ID: {reported_user_id})", inline=False)
        if custom_reason:
            log_embed.add_field(name="📝 Lý do / Chi tiết", value=custom_reason, inline=False)
            
        await admin_channel.send(embed=log_embed)

    try:
        await interaction.user.send(f"💌 **Đã gửi yêu cầu!** Ticket của bạn đã được tạo thành công tại {ticket_channel.mention}. Vui lòng truy cập kênh đó và đợi Admin/Staff giải quyết nhé!")
    except discord.Forbidden:
        pass

    await interaction.followup.send(f"✅ Đã mở ticket thành công! Hãy vào {ticket_channel.mention} để trao đổi.", ephemeral=True)

    # --- NỘI DUNG GỬI VÀO TRONG KÊNH TICKET ---
    embed = discord.Embed(
        title=f"🛠️ Yêu cầu: {ticket_type}",
        color=discord.Color.blue()
    )
    
    desc = f"Xin chào {interaction.user.mention},\n\n"
    if reported_user_id:
        desc += f"**🚨 Đối tượng bị báo cáo:** <@{reported_user_id}>\n"
    if custom_reason:
        desc += f"**📝 Chi tiết vấn đề:** {custom_reason}\n\n"
    else:
        desc += "Vui lòng mô tả chi tiết vấn đề của bạn ở đây.\n\n"
        
    desc += "Đội ngũ Ban Quản Trị sẽ phản hồi bạn sớm nhất có thể."
    embed.description = desc
    embed.set_footer(text="Sử dụng các nút bên dưới để đóng ticket khi xong việc.")
    
    # --- CHUẨN BỊ LỜI PING ĐỘNG THEO LOẠI TICKET ---
    ping_roles = ""
    for role in [admin_role, dev_role, staff_role]:
        if role: 
            ping_roles += f"{role.mention} "
            
    # Tùy biến nội dung ping dựa trên ticket_type
    if reported_user_id:
        ping_msg = f"🔔 {ping_roles}\n🚨 {interaction.user.mention} đã **tố cáo** thành viên <@{reported_user_id}>!"
    elif "Báo lỗi" in ticket_type:
        ping_msg = f"🔔 {ping_roles}\n⚠️ {interaction.user.mention} vừa **{ticket_type}**!"
    else:
        ping_msg = f"🔔 {ping_roles}\n📩 {interaction.user.mention} cần **{ticket_type}**!"
        
    # Gửi tin nhắn ping kèm Embed và View điều khiển
    await ticket_channel.send(
        content=ping_msg,
        embed=embed, 
        view=TicketControlView(interaction.user)
    )

# --- 1. MODAL: TỐ CÁO THÀNH VIÊN ---
class ReportMemberModal(discord.ui.Modal, title="Tố cáo thành viên"):
    member_id = discord.ui.TextInput(
        label="ID Thành viên vi phạm", 
        placeholder="Ví dụ: 856704693215166474", 
        required=True, 
        max_length=25
    )
    reason = discord.ui.TextInput(
        label="Hành vi vi phạm", 
        style=discord.TextStyle.paragraph, 
        placeholder="Mô tả rõ hành vi vi phạm của người này...", 
        required=True, 
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = self.member_id.value.strip()
        
        if not user_id.isdigit():
            return await interaction.followup.send("❌ ID thành viên không hợp lệ (ID chỉ bao gồm các chữ số).", ephemeral=True)
            
        await create_ticket_channel(interaction, "Báo cáo thành viên vi phạm", custom_reason=self.reason.value, reported_user_id=user_id)


# --- 2. SELECT MENU & VIEW: BÁO LỖI BUG ---

class ReportBugModal(discord.ui.Modal):
    def __init__(self, bug_type: str):
        # Discord giới hạn tiêu đề Modal tối đa 45 ký tự nên ta dùng [:45] để cắt bớt nếu lỡ dài quá
        super().__init__(title=f"Báo lỗi: {bug_type}"[:45])
        self.bug_type = bug_type
        
        # Tạo ô nhập liệu cho người dùng
        self.bug_description = discord.ui.TextInput(
            label="Mô tả chi tiết lỗi",
            style=discord.TextStyle.paragraph, # paragraph để có khung nhập chữ to, dễ xuống dòng
            placeholder="Bạn gặp lỗi gì, ở đâu, làm sao để tái hiện lỗi này?",
            required=True,
            max_length=1000
        )
        self.add_item(self.bug_description)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Truyền nội dung mô tả lỗi (bug_description.value) vào phần custom_reason
        await create_ticket_channel(interaction, f"Báo lỗi: {self.bug_type}", custom_reason=self.bug_description.value)


class BugTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Lỗi Bot trong Server", description="Các lỗi liên quan đến bot Discord", emoji="🤖"),
            discord.SelectOption(label="Lỗi Máy chủ Server", description="Lỗi kênh, roles hoặc hệ thống của server", emoji="🖥️"),
            discord.SelectOption(label="Lỗi Web tk.chill", description="Sự cố khi sử dụng Website tk.chill", emoji="🌐"),
            discord.SelectOption(label="Lỗi App tk.chill", description="Sự cố khi sử dụng App tk.chill", emoji="📱"),
        ]
        super().__init__(placeholder="Vui lòng chọn khu vực đang bị lỗi...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_bug = self.values[0]
        # QUAN TRỌNG: Gọi Modal ngay khi người dùng chọn xong (Không dùng defer ở đây nữa vì sẽ làm lỗi Modal)
        await interaction.response.send_modal(ReportBugModal(selected_bug))


class BugTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BugTypeSelect())


# --- 3. MODAL: YÊU CẦU HỖ TRỢ KHÁC ---
class OtherHelpModal(discord.ui.Modal, title="Yêu cầu hỗ trợ chung"):
    reason = discord.ui.TextInput(
        label="Lý do cần hỗ trợ", 
        style=discord.TextStyle.paragraph, 
        placeholder="Hãy mô tả ngắn gọn vấn đề bạn đang gặp phải...", 
        required=True, 
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await create_ticket_channel(interaction, "Yêu cầu hỗ trợ chung", custom_reason=self.reason.value)


# --- 4. GIAO DIỆN CHÍNH CỦA BẢNG TICKET ---
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Báo cáo vi phạm", style=discord.ButtonStyle.blurple, emoji="🚨", custom_id="btn_report_member")
    async def btn_report_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mở Modal nhập ID và lý do
        await interaction.response.send_modal(ReportMemberModal())

    @discord.ui.button(label="Báo lỗi/Bug", style=discord.ButtonStyle.gray, emoji="⚠️", custom_id="btn_report_bug")
    async def btn_report_bug(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mở Select Menu (dạng tin nhắn ẩn)
        await interaction.response.send_message(
            "📌 **Bạn đang gặp lỗi ở khu vực nào?** Vui lòng chọn trong danh sách dưới đây:", 
            view=BugTypeView(), 
            ephemeral=True
        )

    @discord.ui.button(label="Hỗ trợ khác", style=discord.ButtonStyle.green, emoji="📩", custom_id="btn_other_help")
    async def btn_other_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Mở Modal nhập lý do cần hỗ trợ
        await interaction.response.send_modal(OtherHelpModal())

class EditTimeModal(discord.ui.Modal, title="Sửa thời gian Timeout"):
    def __init__(self, admin_view):
        super().__init__()
        self.admin_view = admin_view 
    time_input = discord.ui.TextInput(label="Thời gian mới (Phút)", placeholder="Ví dụ: 60", required=True, max_length=5)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_time = int(self.time_input.value)
            self.admin_view.duration = new_time
            embed = interaction.message.embeds[0]
            embed.set_field_at(2, name="Chi tiết", value=f"Timeout trong **{new_time} phút**", inline=False)
            await interaction.response.edit_message(embed=embed, view=self.admin_view)
        except ValueError:
            await interaction.response.send_message("❌ Vui lòng nhập số phút hợp lệ!", ephemeral=True)

class AdminApprovalView(discord.ui.View):
    def __init__(self, requester: discord.Member, target: discord.Member, action: str, reason: str, duration: int = 0):
        super().__init__(timeout=None)
        self.requester, self.target, self.action = requester, target, action
        self.reason, self.duration = reason, duration
        if action != "TIMEOUT":
            for child in self.children:
                if getattr(child, "custom_id", "") == "edit_time_btn":
                    self.remove_item(child)
                    break

    @discord.ui.button(label="Sửa thời gian", style=discord.ButtonStyle.gray, emoji="✏️", custom_id="edit_time_btn")
    async def edit_time_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction): return await interaction.response.send_message("Không đủ quyền!", ephemeral=True)
        await interaction.response.send_modal(EditTimeModal(self))

    @discord.ui.button(label="DUYỆT", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction): return await interaction.response.send_message("Không đủ quyền!", ephemeral=True)
        await interaction.response.edit_message(content=f"✅ **Đã duyệt** bởi {interaction.user.mention}", view=None, embed=None)

        vote_channel = interaction.guild.get_channel(VOTE_CHANNEL_ID)
        future_timestamp = int(datetime.datetime.now().timestamp() + VOTE_DURATION)
        action_desc = f"**{self.action}**" + (f" ({self.duration} phút)" if self.action == "TIMEOUT" else "")

        embed = discord.Embed(title="⚖️ TÒA ÁN CỘNG ĐỒNG (VOTE KICK)", description="Mọi người hãy bỏ phiếu công tâm!", color=discord.Color.orange())
        embed.add_field(name="Bị cáo", value=self.target.mention, inline=True)
        embed.add_field(name="Đề nghị", value=action_desc, inline=True)
        
        safe_reason = self.reason if (self.reason and len(self.reason.strip()) > 0) else "Không có lý do"
        if len(safe_reason) > 1024: safe_reason = safe_reason[:1021] + "..."
        embed.add_field(name="Lý do", value=safe_reason, inline=False)
        
        embed.add_field(name="Kết thúc", value=f"<t:{future_timestamp}:R>", inline=True)
        
        vote_view = PublicVoteView(self.target, self.action, self.reason, self.duration, self.requester.id)
        msg = await vote_channel.send(content=f"<@&{MEMBER_ROLE_ID}> 📢 **VOTE START!** {self.target.mention} đang bị đề nghị xử lý.", embed=embed, view=vote_view)
        vote_view.message = msg
        await asyncio.sleep(VOTE_DURATION) 
        await vote_view.finish_vote(vote_channel)

    @discord.ui.button(label="TỪ CHỐI", style=discord.ButtonStyle.red, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction): return await interaction.response.send_message("Không đủ quyền!", ephemeral=True)
        await interaction.response.edit_message(content="❌ **Đã từ chối.**", view=None, embed=None)
        vote_channel = interaction.guild.get_channel(VOTE_CHANNEL_ID)
        if vote_channel: await vote_channel.send(f"❌ {self.requester.mention}, yêu cầu xử lý **{self.target.name}** đã bị Admin bác bỏ.")

class ReasonModal(discord.ui.Modal, title="Nhập lý do xử lý"):
    def __init__(self, target: discord.Member, action: str):
        super().__init__()
        self.target, self.action = target, action
    reason_input = discord.ui.TextInput(label="Lý do", style=discord.TextStyle.paragraph, required=True, max_length=1000)
    async def on_submit(self, interaction: discord.Interaction):
        await send_to_admin(interaction, self.target, self.action, self.reason_input.value, 0)

class TimeoutModal(discord.ui.Modal, title="Chi tiết Timeout"):
    def __init__(self, target: discord.Member):
        super().__init__()
        self.target = target
    reason_input = discord.ui.TextInput(label="Lý do", style=discord.TextStyle.paragraph, required=True, max_length=1000)
    time_input = discord.ui.TextInput(label="Thời gian (Phút)", placeholder="Ví dụ: 60", required=True, max_length=5)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes = int(self.time_input.value)
            await send_to_admin(interaction, self.target, "TIMEOUT", self.reason_input.value, minutes)
        except ValueError: await interaction.response.send_message("❌ Thời gian phải là số!", ephemeral=True)

async def send_to_admin(interaction, target, action, reason, duration):
    admin_channel = interaction.guild.get_channel(ADMIN_CHANNEL_ID)
    if not admin_channel: return await interaction.response.send_message("Lỗi kênh Admin.", ephemeral=True)
    embed = discord.Embed(title="📩 YÊU CẦU XỬ LÝ MỚI", color=discord.Color.yellow())
    embed.add_field(name="Người yêu cầu", value=interaction.user.mention, inline=True)
    embed.add_field(name="Đối tượng", value=target.mention, inline=True)
    embed.add_field(name="Hành động", value=f"**{action}**" + (f" ({duration} phút)" if action == "TIMEOUT" else ""), inline=False)
    
    safe_reason = reason if (reason and len(reason.strip()) > 0) else "Không có lý do"
    if len(safe_reason) > 1024: safe_reason = safe_reason[:1021] + "..."
    embed.add_field(name="Lý do", value=safe_reason, inline=False)
    
    await admin_channel.send(embed=embed, view=AdminApprovalView(interaction.user, target, action, reason, duration))
    await interaction.response.send_message("✅ Đã gửi đơn lên Admin.", ephemeral=True)

class ActionSelect(discord.ui.Select):
    def __init__(self, target: discord.Member):
        self.target = target
        options = [
            discord.SelectOption(label="Kick (Đuổi)", value="KICK", emoji="👢"),
            discord.SelectOption(label="Ban (Cấm)", value="BAN", emoji="🔨"),
            discord.SelectOption(label="Timeout (Cấm chat)", value="TIMEOUT", emoji="😶"),
        ]
        super().__init__(placeholder="Chọn hình thức xử lý...", options=options)
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "TIMEOUT": await interaction.response.send_modal(TimeoutModal(self.target))
        else: await interaction.response.send_modal(ReasonModal(self.target, self.values[0]))

class ActionSelectView(discord.ui.View):
    def __init__(self, target: discord.Member):
        super().__init__()
        self.add_item(ActionSelect(target))

@bot.tree.command(name="vote_kick", description="Tạo đơn yêu cầu xử lý thành viên (Tất cả đều dùng được)")
async def vote_kick_command(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        return await interaction.response.send_message("❌ Không hợp lệ.", ephemeral=True)
    await interaction.response.send_message("Bạn muốn xử lý người này như thế nào?", view=ActionSelectView(member), ephemeral=True)

class ApprovalView(discord.ui.View):
    def __init__(self, requester: discord.Member, command_name: str, command_desc: str):
        super().__init__(timeout=None)
        self.requester, self.command_name, self.command_desc = requester, command_name, command_desc

    @discord.ui.button(label="Phê Duyệt", style=discord.ButtonStyle.green, emoji="✅")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"✅ **ĐÃ PHÊ DUYỆT** yêu cầu lệnh `/{self.command_name}`.", view=None, embed=None)
        try: await self.requester.send(f"✅ Yêu cầu lệnh `/{self.command_name}` đã được duyệt.")
        except: pass

    @discord.ui.button(label="Từ Chối", style=discord.ButtonStyle.red, emoji="❌")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"❌ **ĐÃ TỪ CHỐI** yêu cầu lệnh `/{self.command_name}`.", view=None, embed=None)
        try: await self.requester.send(f"❌ Yêu cầu lệnh `/{self.command_name}` đã bị từ chối.")
        except: pass

@bot.tree.command(name="request_function", description="Gửi yêu cầu thêm tính năng mới")
@app_commands.default_permissions(moderate_members=True) 
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def request_function(interaction: discord.Interaction, name: str, description: str):
    owner = await bot.fetch_user(OWNER_ID)
    if not owner: return await interaction.response.send_message("Không tìm thấy Owner.", ephemeral=True)
    embed = discord.Embed(title="📩 YÊU CẦU TÍNH NĂNG MỚI", color=discord.Color.gold())
    embed.add_field(name="Người yêu cầu", value=interaction.user.mention)
    embed.add_field(name="Tên lệnh", value=f"`/{name}`")
    embed.add_field(name="Mô tả", value=description)
    await owner.send(embed=embed, view=ApprovalView(interaction.user, name, description))
    await interaction.response.send_message("✅ Đã gửi yêu cầu tới Admin.", ephemeral=True)

@bot.tree.command(name="ban_time", description="Tước quyền bằng role ban có thời hạn")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def ban_time(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Vi phạm tạm thời"):
    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
    if not ban_role or not member_role: return await interaction.response.send_message("❌ Lỗi Role.", ephemeral=True)
    
    try:
        roles_to_remove = [role for role in member.roles if role.name != "@everyone"]
        await member.remove_roles(*roles_to_remove, reason="Ban tạm thời")
        audit_reason = f"{reason} - {minutes} phút"[:500]
        await member.add_roles(ban_role, reason=audit_reason)
        await interaction.response.send_message(f"🚨 Đã tước quyền {member.mention} trong **{minutes} phút**.")
        
        msg = await send_punishment_log(interaction.guild, member, "Ban Tạm Thời (Role)", reason, f"{minutes} phút", duration_minutes=minutes)
        
        # --- LƯU MONGODB ĐỂ VÒNG LẶP XỬ LÝ UNBAN ---
        if msg:
            expire_time = datetime.datetime.now().timestamp() + (minutes * 60)
            await punishment_collection.insert_one({
                "message_id": msg.id,
                "channel_id": msg.channel.id,
                "target_id": member.id,
                "expire_at": expire_time,
                "action_type": "soft_ban", # Phải báo cho DB biết đây là tước Role
                "status": "active"
            })

    except discord.Forbidden:
        return await interaction.response.send_message("❌ Bot không đủ quyền.", ephemeral=True)

@bot.tree.command(name="giverole", description="Trao role cho thành viên")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def giverole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    if role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id: 
        return await interaction.response.send_message("❌ Không thể trao role cao hơn hoặc bằng bạn!", ephemeral=True)
    await member.add_roles(role)
    await interaction.response.send_message(f"✅ Đã thêm role {role.mention} cho {member.mention}.")

@bot.tree.command(name="unrole", description="Xóa role của thành viên")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def unrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    if role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id: 
        return await interaction.response.send_message("❌ Không thể xoá role cao hơn hoặc bằng bạn!", ephemeral=True)
    await member.remove_roles(role)
    await interaction.response.send_message(f"✅ Đã xoá role {role.mention} khỏi {member.mention}.")

@bot.tree.command(name="kick", description="Kick thành viên khỏi server")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Không có lý do"):
    await member.kick(reason=reason[:500])
    await interaction.response.send_message(f"👋 Đã kick {member.name}. Lý do: {reason}")
    
    # --- GỌI HÀM LOG XỬ PHẠT ---
    await send_punishment_log(interaction.guild, member, "Kick (Đuổi)", reason)

@bot.tree.command(name="ban", description="Tước mọi quyền (Ban mềm bằng Role)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def ban_member(interaction: discord.Interaction, member: discord.Member, reason: str = "Vi phạm"):
    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    try:
        roles_to_remove = [role for role in member.roles if role.name != "@everyone"]
        await member.remove_roles(*roles_to_remove)
        await member.add_roles(ban_role, reason=reason[:500])
        await interaction.response.send_message(f"🚨 Đã tước quyền hoàn toàn (BAN MỀM) {member.mention}.")
        
        # --- GHI LOG (Không có phút, không lưu MongoDB vì đây là ban vĩnh viễn) ---
        await send_punishment_log(interaction.guild, member, "Ban Mềm (Role)", reason)
        
    except Exception as e: 
        await interaction.response.send_message(f"❌ Lỗi: {e}", ephemeral=True)

@bot.tree.command(name="unban", description="Gỡ tước quyền (Unban mềm)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def unban_member(interaction: discord.Interaction, member: discord.Member):
    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    if ban_role in member.roles:
        await member.remove_roles(ban_role)
        await interaction.response.send_message(f"✅ Đã gỡ phạt cho {member.mention}.")
    else:
        await interaction.response.send_message(f"⚠️ {member.mention} không bị phạt.", ephemeral=True)

@bot.tree.command(name="infor", description="Xem thông tin thành viên")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def userinfo(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(title=f"Thông tin: {member.name}", color=discord.Color.blue())
    embed.add_field(name="ID", value=member.id, inline=False)
    embed.add_field(name="Ngày tạo", value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Ngày vào", value=member.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="mute", description="Cấm chat (Timeout) người dùng")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def mute_member(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Không có lý do"):
    try:
        await member.timeout(datetime.timedelta(minutes=minutes), reason=reason[:500])
        await interaction.response.send_message(f"😶 Đã cấm chat {member.mention} trong **{minutes} phút**.\n📝 Lý do: {reason}")
        
        msg = await send_punishment_log(interaction.guild, member, "Timeout (Cấm chat)", reason, f"{minutes} phút", duration_minutes=minutes)
        
        if msg:
            expire_time = datetime.datetime.now().timestamp() + (minutes * 60)
            await punishment_collection.insert_one({
                "message_id": msg.id,
                "channel_id": msg.channel.id,
                "target_id": member.id,
                "expire_at": expire_time,
                "action_type": "timeout",
                "status": "active"
            })

    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot không đủ quyền Timeout (Role của họ cao hơn bot).", ephemeral=True)
        
@bot.tree.command(name="unmute", description="Gỡ cấm chat (Timeout)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def unmute_member(interaction: discord.Interaction, member: discord.Member, reason: str = "Đã được gỡ cấm chat"):
    try:
        await member.timeout(None, reason=reason[:500])
        await interaction.response.send_message(f"🔊 Đã gỡ cấm chat cho {member.mention}.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot không đủ quyền.", ephemeral=True)

@bot.tree.command(name="setup_ticket", description="Hiển thị bảng tạo Ticket")
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
@app_commands.default_permissions(moderate_members=True) 
async def setup_ticket(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛠️ TRUNG TÂM HỖ TRỢ THÀNH VIÊN",
        description=(
            "Bạn đang gặp sự cố, muốn tố cáo thành viên vi phạm, hoặc cần liên hệ với Ban Quản Trị?\n\n"
            "**Hãy chọn một trong các nút bên dưới để mở kênh trò chuyện riêng tư.**\n\n"
            "⚠️ *Lưu ý: Không tạo ticket để trêu đùa hoặc spam để tránh bị xử phạt.*"
        ),
        color=discord.Color.teal()
    )
    embed.set_footer(text="Hệ thống Ticket tự động")
    
    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message("✅ Đã tạo bảng Ticket thành công!", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot đã online: {bot.user}')

bot.run(TOKEN)
