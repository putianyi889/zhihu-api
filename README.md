# zhihu-api

一个极简的 Python 包，通过知乎网页公开使用的数据接口读取公开数据。第一版支持：

- 用户 `url_token` 与用户 `id` 互相查询
- 通过专栏文章 ID（或文章链接）获取文章标题、专栏标题、作者、发布时间等元数据

> 本项目使用知乎网页端公开但非官方开放的接口。接口字段和访问策略可能变化，也可能要求浏览器 Cookie 或验证码。请遵守知乎服务条款并控制请求频率。

## 安装

```bash
pip install git+https://github.com/putianyi889/zhihu-api.git@v0.1.0
```

从源码安装：

```bash
git clone https://github.com/putianyi889/zhihu-api.git
cd zhihu-api
pip install .
```

仅依赖 Python 标准库，支持 Python 3.9+。

## Python 用法

```python
from zhihu_api import ZhihuClient

client = ZhihuClient()

# url_token -> id
user_id = client.get_user_id("excited-vczh")
print(user_id)  # 0970f947b898ecc0ec035f9126dd4e08

# id -> url_token
url_token = client.get_url_token("0970f947b898ecc0ec035f9126dd4e08")
print(url_token)  # excited-vczh

# 同时拿到两个标识和用户昵称
user = client.get_user("excited-vczh")
print(user.id, user.url_token, user.name)

# 专栏文章元数据
article = client.get_article("140036646")
print(article.title)          # 文章标题
print(article.column_title)   # 专栏标题
print(article.author_name)    # 文章作者昵称
print(article.column_author)  # 专栏作者（若接口返回，否则回退到文章作者）
print(article.published_at)   # UTC datetime，文章发布时间
print(article.as_dict())      # 结构化字典，便于序列化
```

也支持传入链接：

```python
client.get_user_id("https://www.zhihu.com/people/excited-vczh")
client.get_article("https://zhuanlan.zhihu.com/p/140036646")
```

如果知乎要求登录态或验证，可传入浏览器 Cookie：

```python
client = ZhihuClient(cookie="z_c0=你的_token; ...")
```

也可以直接使用模块级便捷函数：

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
```

`article` 命令输出 JSON，包含 `title`、`column_title`、`author` 和 `published_at` 等字段。全局选项支持 `--cookie` 与 `--timeout`。

## 数据来源

- 用户标识：`GET /api/v4/members/{id_or_url_token}?include=id,url_token,name`
- 文章元数据：`GET /api/v4/articles/{article_id}?include=created,updated,title,author,url,column`

其中 `created` 是 Unix 秒级时间戳，包内会转换为 UTC `datetime`。如果文章响应中包含 `column`，还会返回专栏的 ID、标题、作者和创建时间。

## 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
