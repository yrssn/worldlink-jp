"""RBAC 运行时：内置菜单/角色种子数据、权限判定、数据归属范围。

设计要点
--------
1. **路由级权限**：一个 ``Menu`` = 一个前端路由 + 一组后端 API 前缀。
   用户能访问的菜单 = 其所有启用角色关联菜单的并集；超级管理员拥有全部。
2. **后端同步校验**：``api_prefixes`` 让后端按请求路径反查所需菜单，
   避免只在前端隐藏菜单（见 ``app.core.permission_guard``）。
3. **数据归属**：
   - ``SHARED_TABLES`` 里的表属于「团队共享」数据，所有登录用户都能看；
   - 其余表按 ``owner_id`` 隔离，只有创建人可见；
   - 角色 ``data_scope=all``（超级管理员）可见全部数据。
"""
from __future__ import annotations

from app.models.rbac import ApiEnforceMode, DataScope, MenuType

SUPER_ADMIN_ROLE_CODE = "super_admin"
DEFAULT_USER_ROLE_CODE = "normal_user"

#: 团队共享的数据表：这些模块里的数据不区分创建人，所有人都能查看/使用。
#: 之所以共享，是因为它们都属于「公共配置/公共素材」，各人各存一份没有意义。
SHARED_TABLES: set[str] = {
    "llm_providers",  # 大模型厂商配置
    "prompt_templates",  # 提示词模板
    "dm_categories",  # 私信分类
    "dm_contents",  # 私信内容库
    "bitbrowser_platforms",  # 自建平台（窗口分类字典 + 达人关联平台）
    "countries",  # 国家字典
    "email_accounts",  # 注册用邮箱池
    "apify_keys",  # Apify Key 池（本身就没有 owner_id）
}

#: 按创建人隔离的数据表（仅作文档说明，实际逻辑为「不在 SHARED_TABLES 即隔离」）：
#: scrape_tasks / posts / fb_group_scrapes / fb_group_pull_tasks / fb_group_posts /
#: influencers / social_accounts / influencer_scrape_tasks / dm_outreach_logs /
#: bitbrowser_windows / bitbrowser_window_catalog / apify_signup_tasks
OWNED_TABLES_DOC = "谁创建谁可见，超级管理员（data_scope=all）可见全部"


class MenuSeed:
    """内置菜单定义（与前端 ``src/router/index.ts`` 的 meta.code 一一对应）。"""

    def __init__(
        self,
        code: str,
        title: str,
        *,
        path: str | None = None,
        icon: str | None = None,
        type: MenuType = MenuType.menu,
        is_hidden: bool = False,
        api_prefixes: list[str] | None = None,
        api_enforce_mode: ApiEnforceMode = ApiEnforceMode.all,
        children: list["MenuSeed"] | None = None,
    ) -> None:
        self.code = code
        self.title = title
        self.path = path
        self.icon = icon
        self.type = type
        self.is_hidden = is_hidden
        self.api_prefixes = api_prefixes or []
        self.api_enforce_mode = api_enforce_mode
        self.children = children or []


# ``api_enforce_mode=write``：该模块的数据会被别的页面读取（例如建任务时要选提示词模板、
# 私信建联时要读内容库），所以读接口放开、只拦写操作，避免出现「有页面没数据」的坑。
MENU_SEEDS: list[MenuSeed] = [
    MenuSeed(
        "llm",
        "大模型",
        icon="Cpu",
        type=MenuType.catalog,
        children=[
            MenuSeed(
                "llm:providers",
                "厂商配置",
                path="/llm/providers",
                api_prefixes=["/api/v1/llm/providers"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
            MenuSeed(
                "llm:prompts",
                "提示词模板",
                path="/llm/prompts",
                api_prefixes=["/api/v1/llm/prompts"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
        ],
    ),
    MenuSeed(
        "bitbrowser",
        "比特抓取",
        icon="Monitor",
        type=MenuType.catalog,
        children=[
            MenuSeed(
                "bitbrowser:connect",
                "本机连接",
                path="/bitbrowser/connect",
                api_prefixes=["/api/v1/bitbrowser/settings"],
            ),
            MenuSeed(
                "bitbrowser:windows",
                "浏览器窗口",
                path="/bitbrowser/windows",
                api_prefixes=["/api/v1/bitbrowser/windows"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
            MenuSeed(
                "bitbrowser:saved",
                "系统登记",
                path="/bitbrowser/saved",
                api_prefixes=["/api/v1/bitbrowser/catalog"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
            MenuSeed(
                "bitbrowser:platforms",
                "平台管理",
                path="/bitbrowser/platforms",
                api_prefixes=["/api/v1/bitbrowser/platforms"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
        ],
    ),
    MenuSeed(
        "automation",
        "账号自动化",
        icon="Message",
        type=MenuType.catalog,
        children=[
            MenuSeed(
                "email:accounts",
                "邮箱管理",
                path="/email/accounts",
                api_prefixes=["/api/v1/email/accounts"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
        ],
    ),
    MenuSeed(
        "scraper",
        "抓取器",
        icon="Search",
        type=MenuType.catalog,
        children=[
            MenuSeed(
                "scraper:tasks",
                "抓取任务",
                path="/scraper/tasks",
                api_prefixes=["/api/v1/scraper/tasks"],
            ),
            MenuSeed(
                "scraper:task-detail",
                "任务详情",
                path="/scraper/tasks/:id",
                is_hidden=True,
                api_enforce_mode=ApiEnforceMode.off,
            ),
            MenuSeed(
                "scraper:fb-groups",
                "Facebook群组维度",
                path="/scraper/facebook-groups",
                api_prefixes=["/api/v1/scraper/fb-group-scrapes"],
            ),
            MenuSeed(
                "scraper:apify-keys",
                "Apify Key 管理",
                path="/scraper/apify-keys",
                api_prefixes=["/api/v1/scraper/apify-keys"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
        ],
    ),
    MenuSeed(
        "dm",
        "私信内容",
        icon="ChatDotRound",
        type=MenuType.catalog,
        children=[
            MenuSeed(
                "dm:contents",
                "内容库",
                path="/dm/contents",
                api_prefixes=["/api/v1/dm/contents", "/api/v1/dm/uploads"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
            MenuSeed(
                "dm:categories",
                "分类管理",
                path="/dm/categories",
                api_prefixes=["/api/v1/dm/categories"],
                api_enforce_mode=ApiEnforceMode.write,
            ),
        ],
    ),
    MenuSeed(
        "influencers",
        "建联达人",
        path="/influencers",
        icon="User",
        api_prefixes=["/api/v1/influencers"],
    ),
    MenuSeed(
        "influencer:detail",
        "达人详情",
        path="/influencers/:id",
        is_hidden=True,
        api_enforce_mode=ApiEnforceMode.off,
    ),
    MenuSeed(
        "countries",
        "国家管理",
        path="/countries",
        icon="LocationInformation",
        api_prefixes=["/api/v1/countries"],
        api_enforce_mode=ApiEnforceMode.write,
    ),
    MenuSeed(
        "system",
        "系统管理",
        icon="Setting",
        type=MenuType.catalog,
        children=[
            MenuSeed(
                "system:users",
                "用户列表",
                path="/system/users",
                api_prefixes=["/api/v1/system/users"],
            ),
            MenuSeed(
                "system:roles",
                "角色权限",
                path="/system/roles",
                api_prefixes=["/api/v1/system/roles"],
            ),
            MenuSeed(
                "system:menus",
                "路由列表",
                path="/system/menus",
                api_prefixes=["/api/v1/system/menus"],
            ),
        ],
    ),
]


def flatten_seeds(
    seeds: list[MenuSeed] | None = None, parent: MenuSeed | None = None
) -> list[tuple[MenuSeed, MenuSeed | None]]:
    """把树状 seed 拍平成 ``(seed, parent_seed)`` 列表，保持先父后子的顺序。"""
    result: list[tuple[MenuSeed, MenuSeed | None]] = []
    for seed in seeds if seeds is not None else MENU_SEEDS:
        result.append((seed, parent))
        result.extend(flatten_seeds(seed.children, seed))
    return result


#: 内置「普通用户」角色默认拥有的菜单：除「系统管理」外的全部业务菜单。
#: 日常干活的员工默认就能用全部业务页面，只是看不到用户/角色/路由配置；
#: 要收窄到更小范围，在「角色权限」页新建角色自行勾选即可。
SYSTEM_MENU_CODE = "system"
DEFAULT_USER_MENU_CODES: list[str] = [
    seed.code
    for seed, parent in flatten_seeds()
    if seed.code != SYSTEM_MENU_CODE
    and (parent is None or parent.code != SYSTEM_MENU_CODE)
]

ROLE_SEEDS: list[dict] = [
    {
        "code": SUPER_ADMIN_ROLE_CODE,
        "name": "超级管理员",
        "remark": "拥有全部菜单与全部数据可见范围，不可删除",
        "data_scope": DataScope.all,
        "is_builtin": True,
        "sort_order": 0,
        "menu_codes": None,  # None = 全部菜单
    },
    {
        "code": DEFAULT_USER_ROLE_CODE,
        "name": "普通用户",
        "remark": "只看自己创建的数据；公共配置类模块共享",
        "data_scope": DataScope.own,
        "is_builtin": True,
        "sort_order": 10,
        "menu_codes": DEFAULT_USER_MENU_CODES,
    },
]
