***往世乐土推荐刻印***

图片资源目录：`$RES_DIR/img/ElysianRealm`

## 使用方式

- `刻印 角色别名`：从最新的 6 个版本目录由新到旧查询角色刻印图，命中后返回该目录下全部匹配图片和目录名；6 个目录都找不到时回退到资源根目录。
- `刻印更新`：SU 用户自动拉取米游社账号 `5625196` 的最新一期推荐角色 BUFF 表并更新资源。
- `刻印更新 https://www.miyoushe.com/bh3/article/75733395`：SU 用户按指定帖子更新资源。

更新任务会下载帖子正文图片，按标题生成版本目录，例如 `V8.9一期` 会写入
`$RES_DIR/img/ElysianRealm/v8.9.1`。一期帖子会刷新女武神 wiki 图片索引，再用
OpenCV AKAZE 匹配左上角角色 poster，并把攻略图重命名为女武神名称。

资源目录只保留最新的 6 个 `vX.Y.Z` 版本目录。更新完成后会淘汰更旧的版本目录，
并把被淘汰目录里的图片移动到资源根目录，作为最近 6 次攻略都没有覆盖某个女武神时
的兜底图。

## 命令行维护

单帖更新：

```powershell
D:\code\HoshinoBot\.venv\Scripts\python.exe download_miyoushe_elysian_realm_post.py "https://www.miyoushe.com/bh3/article/75733395"
```

账号批量更新：

```powershell
D:\code\HoshinoBot\.venv\Scripts\python.exe download_miyoushe_user_elysian_posts.py "https://www.miyoushe.com/bh3/accountCenter/postList?id=5625196"
```

只识别某个版本目录：

```powershell
D:\code\HoshinoBot\.venv\Scripts\python.exe identify_valkyrie_guide_images.py --guide-dir "D:\code\HoshinoBot\res\img\ElysianRealm\v8.9.1" --rename
```

刷新女武神 wiki 数据和本地图片索引：

```powershell
D:\code\HoshinoBot\.venv\Scripts\python.exe scrape_bh3_valkyries.py
D:\code\HoshinoBot\.venv\Scripts\python.exe download_bh3_valkyrie_images.py
```

`scrape_bh3_valkyries.py` 会同步更新 `alias.json`：新女武神会自动加入，
已有女武神只合并 wiki 里的新别名，不覆盖手动添加的别名。
