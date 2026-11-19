# zhihu-api

一个极简的 Python 包，读取知乎公开数据。v0.2 起默认不再直连知乎接口，而是通过公开 Reader 代理读取渲染后的网页与公开成员接口，以规避本地 IP 被知乎反爬拦截的问题。

支持：

- 用户 `url_token` 与用户 `id` 互相查询
- 通过专栏文章 ID（或文章链接）获取文章标题、专栏标题、作者、专栏作者、页面显示的时间

> 本项目只读取公开页面，不绕过登录或验证码。请遵守知乎服务条款并控制请求频率。

## 安装

```bash
pip install git+https://github.com/putianyi889/zhihu-api.git@v0.2.1
```

仅依赖 Python 标准库，支持 Python 3.9+。

## 工作原理

默认 `source="reader"`：

- 用户标识：通过 `r.jina.ai` 读取 `/api/v4/members/{id_or_url_token}?include=id,url_token,name`
- 文章元数据：读取渲染后的 `zhuanlan.zhihu.com/p/{id}` 页面，优先解析内嵌 `js-initialData` JSON，拿到精确的 `created` / `updated`、作者 ID、专栏与专栏作者；内嵌数据不可用时回退到页面文本解析
- 主动限流：Reader 请求默认每 3 秒一次（对应匿名 20 RPM），重试也计入间隔；可用 `reader_min_interval` 调整，设为 `0` 可关闭

也可用 `source="direct"` 直连知乎接口。若本机网络未被拦截，直连模式能拿到接口中的精确 `created` 时间戳；可配合浏览器 Cookie 使用。

如果不想使用默认公共代理，可设置自己的 Jina API Key（环境变量 `JINA_API_KEY` 或 `reader_api_key` 参数）提高限额。注意：Reader 模式下请求 URL 会发送给第三方公共服务，请勿传入 Cookie。

## Python 用法

```python
from zhihu_api import ZhihuClient

client = ZhihuClient()

# url_token -> id
print(client.get_user_id("excited-vczh"))

# id -> url_token
print(client.get_url_token("0970f947b898ecc0ec035f9126dd4e08"))

# 同时拿到两个标识
user = client.get_user("excited-vczh")
print(user.id, user.url_token, user.name)

# 专栏文章元数据
article = client.get_article("140036646")
print(article.title)          # 文章标题
print(article.column_title)   # 专栏标题
print(article.author_name)    # 文章作者昵称
print(article.column_author)  # 专栏作者
print(article.time_text)      # 页面原文，例如 "编辑于 2020-06-15 02:25"
print(article.published_at)   # 页面显示"发布于"时为 UTC datetime
print(article.updated_at)     # 页面显示"编辑于"时为 UTC datetime
print(article.as_dict())
```

也支持传入链接：

```python
client.get_user_id("https://www.zhihu.com/people/excited-vczh")
client.get_article("https://zhuanlan.zhihu.com/p/140036646")
```

直连模式：

```python
client = ZhihuClient(source="direct", cookie="z_c0=你的_token; ...")
article = client.get_article("140036646")
print(article.published_at)  # 来自接口 created 字段
```

模块级便捷函数：

```python
from zhihu_api import get_article, get_url_token, get_user_id

get_user_id("excited-vczh")
get_url_token("0970f947b898ecc0ec035f9126dd4e08")
get_article("140036646")
```

## 命令行

```bash
zhihu-api user-id excited-vczh
zhihu-api url-token 0970f947b898ecc0ec035f9126dd4e08
zhihu-api article 140036646

# 使用直连模式
zhihu-api --source direct article 140036646
```

`article` 命令输出 JSON，包含 `title`、`column_title`、`author`、`time_text`、`published_at`、`updated_at` 等字段。全局选项支持 `--source`、`--cookie`、`--reader-api-key`、`--reader-min-interval`、`--timeout`。

## 时间字段说明

- 正常情况下从页面内嵌 JSON 读取 `created` / `updated` Unix 时间戳，`published_at` 即精确发布时间，`updated_at` 为最后修改时间。
- `time_text` 是按北京时间格式化的可读文本，`time_kind` 为“发布于”或“编辑于”。
- 若内嵌 JSON 不可用（页面结构变化或代理未返回脚本），会回退到页面文本解析；此时页面只显示“编辑于”时 `published_at` 为 `None`，修改时间写入 `updated_at`，原始文本保留在 `time_text`。
- 直连模式同样读取接口的 `created`，可拿到精确发布时间。

## 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
