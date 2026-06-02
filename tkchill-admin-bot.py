import discord
from discord import app_commands, ui
from discord.ext import commands, tasks # Thêm tasks
import asyncio
import datetime
import os
from aiohttp import web
import aiohttp

# --- CẤU HÌNH (BẠN CẦN ĐIỀN ĐÚNG ID VÀO ĐÂY) ---
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = 1365693391668777051
ADMIN_CHANNEL_ID = 1448258683627638895
BAN_ROLE_ID = 1408787259322273913
VOTE_CHANNEL_ID = 1456467745909637240
MEMBER_ROLE_ID = 1375110178868826142
OWNER_ID = 856704693215166474
MARKETPLACE_CHANNEL_ID = 1461357458252365984

# --- CẤU HÌNH VOTE ---
VOTE_DURATION = 900  # 15 phút
MIN_VOTES_REQUIRED = 4
ALLOWED_ROLES = ["Admin", "DEV", "STAFF"]

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
        print(">> Đã đồng bộ tất cả lệnh Slash Commands!")
        
        # Chạy Web Server ngầm
        bot.loop.create_task(start_web_server())
        # Bắt đầu vòng lặp Ping
        self.ping_bot1.start()

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # ... (Giữ nguyên phần code bắt lỗi cũ của bạn) ...
        if isinstance(error, app_commands.MissingAnyRole):
            await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)
        else:
            print(f"Lỗi: {error}")

    # === VÒNG LẶP ĐI PING BOT 1 ===
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

# --- HÀM KIỂM TRA QUYỀN CHO NÚT BẤM (VIEWS) ---
def has_permission(interaction: discord.Interaction) -> bool:
    user_role_names = [role.name for role in interaction.user.roles]
    return any(role_name in user_role_names for role_name in ALLOWED_ROLES)
    
# ==============================================================================
#                        HỆ THỐNG VOTE KICK (TẤT CẢ ĐỀU THẤY)
# ==============================================================================
# (Các class PublicVoteView, EditTimeModal, AdminApprovalView, ReasonModal, 
# TimeoutModal, ActionSelect, ActionSelectView giữ nguyên logic của bạn)

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
                if self.action == "KICK":
                    await self.target.kick(reason=f"Vote: {self.reason}")
                    await channel.send(f"👋 Đã Kick {self.target.mention}.")
                elif self.action == "BAN":
                    await self.target.ban(reason=f"Vote: {self.reason}")
                    await channel.send(f"🚨 Đã Ban {self.target.mention}.")
                elif self.action == "TIMEOUT":
                    await self.target.timeout(datetime.timedelta(minutes=self.duration), reason=f"Vote: {self.reason}")
                    await channel.send(f"😶 Đã Timeout {self.target.mention} trong {self.duration} phút.")
            except Exception as e:
                await channel.send(f"⚠️ Lỗi thực thi: {e}")
        else:
            res_embed.color = discord.Color.green()
            res_embed.description = f"🛡️ **GIỮ LẠI.** ({'Hòa phiếu' if agrees == disagrees else 'Phản đối thắng'}).\n👍 Đồng ý: {agrees}\n👎 Phản đối: {disagrees}"

        if self.message:
            try: await self.message.edit(view=None, embed=res_embed)
            except: pass

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
        embed.add_field(name="Lý do", value=self.reason, inline=False)
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
    reason_input = discord.ui.TextInput(label="Lý do", style=discord.TextStyle.paragraph, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await send_to_admin(interaction, self.target, self.action, self.reason_input.value, 0)

class TimeoutModal(discord.ui.Modal, title="Chi tiết Timeout"):
    def __init__(self, target: discord.Member):
        super().__init__()
        self.target = target
    reason_input = discord.ui.TextInput(label="Lý do", style=discord.TextStyle.paragraph, required=True)
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
    embed.add_field(name="Lý do", value=reason, inline=False)
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

# --- LỆNH VOTE KICK CÔNG KHAI ---
@bot.tree.command(name="vote_kick", description="Tạo đơn yêu cầu xử lý thành viên (Tất cả đều dùng được)")
async def vote_kick_command(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        return await interaction.response.send_message("❌ Không hợp lệ.", ephemeral=True)
    await interaction.response.send_message("Bạn muốn xử lý người này như thế nào?", view=ActionSelectView(member), ephemeral=True)


# ==============================================================================
#            CÁC LỆNH SLASH DÀNH RIÊNG CHO ADMIN / DEV / STAFF (BỊ ẨN)
# ==============================================================================
# default_permissions(moderate_members=True) giúp ẨN LỆNH khỏi người dùng thường
# checks.has_any_role đảm bảo người dùng có 1 trong 3 role mới thực thi được.

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
        await member.add_roles(ban_role, reason=f"{reason} - {minutes} phút")
        await interaction.response.send_message(f"🚨 Đã tước quyền {member.mention} trong **{minutes} phút**.")
    except discord.Forbidden:
        return await interaction.response.send_message("❌ Bot không đủ quyền.", ephemeral=True)
    
    await asyncio.sleep(minutes * 60)
    try:
        member_refetched = interaction.guild.get_member(member.id) 
        if member_refetched and ban_role in member_refetched.roles:
            await member_refetched.remove_roles(ban_role)
            await member_refetched.add_roles(member_role)
            await interaction.channel.send(f"✅ {member_refetched.mention} đã hết thời hạn phạt.")
    except Exception as e: print(f"Lỗi unban: {e}")

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
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👋 Đã kick {member.name}. Lý do: {reason}")

@bot.tree.command(name="ban", description="Tước mọi quyền (Ban mềm bằng Role)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def ban_member(interaction: discord.Interaction, member: discord.Member, reason: str = "Vi phạm"):
    ban_role = interaction.guild.get_role(BAN_ROLE_ID)
    try:
        roles_to_remove = [role for role in member.roles if role.name != "@everyone"]
        await member.remove_roles(*roles_to_remove)
        await member.add_roles(ban_role, reason=reason)
        await interaction.response.send_message(f"🚨 Đã tước quyền hoàn toàn (BAN MỀM) {member.mention}.")
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
        await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
        await interaction.response.send_message(f"😶 Đã cấm chat {member.mention} trong **{minutes} phút**.\n📝 Lý do: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot không đủ quyền Timeout (Role của họ cao hơn bot).", ephemeral=True)
        
@bot.tree.command(name="unmute", description="Gỡ cấm chat (Timeout)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_any_role(*ALLOWED_ROLES)
async def unmute_member(interaction: discord.Interaction, member: discord.Member, reason: str = "Đã được gỡ cấm chat"):
    try:
        await member.timeout(None, reason=reason)
        await interaction.response.send_message(f"🔊 Đã gỡ cấm chat cho {member.mention}.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot không đủ quyền.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot đã online: {bot.user}')

bot.run(TOKEN)
