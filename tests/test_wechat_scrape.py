import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# 动态将 scripts 目录加入环境变量
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

# 导入爬虫脚本 (假定你的文件名叫 wechat_article_scrape.py)
import wechat_article_scrape as scraper

class TestWechatScraper:
    """测试微信爬虫的 ETL 流程 (包含状态管理和文件合并)"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, tmp_path):
        """
        核心隔离机制：每次运行测试前，把脚本里的硬编码路径全替换成 pytest 的临时目录(tmp_path)
        防止测试过程中的假数据污染了你真实项目里的 data 文件夹！
        """
        self.original_data_dir = scraper.DATA_DIR
        self.original_temp_dir = scraper.TEMP_DIR
        self.original_state_file = scraper.STATE_FILE
        self.original_final_file = scraper.FINAL_FILE

        scraper.DATA_DIR = str(tmp_path / "data")
        scraper.TEMP_DIR = str(tmp_path / "data" / "temp_chunks")
        scraper.STATE_FILE = str(tmp_path / "data" / "scraper_state.json")
        scraper.FINAL_FILE = str(tmp_path / "data" / "wechat_articles_all.json")

        scraper.init_environment()
        
        yield  # 让测试函数运行
        
        # 测试结束，还原环境 (可选，但好习惯)
        scraper.DATA_DIR = self.original_data_dir
        scraper.TEMP_DIR = self.original_temp_dir
        scraper.STATE_FILE = self.original_state_file
        scraper.FINAL_FILE = self.original_final_file

    def test_state_management_serialization(self):
        """测试状态的存取逻辑：重点测试 set 集合转 JSON 列表是否正常"""
        # 1. 构造一个假状态 (注意 seen_links 在内存里是 set)
        mock_state = {
            "begin": 40,
            "total_saved": 40,
            "valid_count": 35,
            "seen_links": {"linkA", "linkB"}
        }

        # 2. 保存状态
        scraper.save_state(mock_state)

        # 3. 验证文件是否生成，并且 JSON 里是列表
        assert os.path.exists(scraper.STATE_FILE)
        with open(scraper.STATE_FILE, "r") as f:
            saved_data = json.load(f)
            assert isinstance(saved_data["seen_links"], list)

        # 4. 重新加载状态，验证是否成功转回 set
        loaded_state = scraper.load_state()
        assert loaded_state["begin"] == 40
        assert isinstance(loaded_state["seen_links"], set)
        assert "linkA" in loaded_state["seen_links"]

    def test_merge_and_cleanup(self, tmp_path):
        """测试最后的分块合并与无痕清理逻辑"""
        # 1. 在临时目录伪造两个 batch 文件
        batch1 = [{"title": "文章1", "link": "url1"}]
        batch2 = [{"title": "文章2", "link": "url2"}]
        
        with open(os.path.join(scraper.TEMP_DIR, "batch_0.json"), "w") as f:
            json.dump(batch1, f)
        with open(os.path.join(scraper.TEMP_DIR, "batch_20.json"), "w") as f:
            json.dump(batch2, f)
            
        # 创建一个假的状态文件用于模拟真实环境
        with open(scraper.STATE_FILE, "w") as f:
            json.dump({"begin": 40}, f)

        mock_state = {"total_saved": 2, "valid_count": 2}

        # 2. 触发合并
        scraper.merge_and_cleanup(mock_state)

        # 3. 验证合并结果
        assert os.path.exists(scraper.FINAL_FILE)
        with open(scraper.FINAL_FILE, "r") as f:
            final_data = json.load(f)
            assert len(final_data) == 2
            assert final_data[0]["title"] == "文章1"
            assert final_data[1]["title"] == "文章2"

        # 4. 验证战场清理 (临时文件夹和状态文件必须被干掉)
        assert not os.path.exists(scraper.TEMP_DIR)
        assert not os.path.exists(scraper.STATE_FILE)

    @patch('wechat_article_scrape.requests.get')
    def test_api_network_error_handling(self, mock_get):
        """
        测试核心的网路请求！我们拦截 requests.get，强制它抛出一个 Timeout 异常。
        爬虫在下载单篇文章失败时，应该静默处理并赋予 content = ""，而不是直接崩溃。
        """
        # 模拟列表 API 正常返回数据
        mock_list_response = MagicMock()
        mock_list_response.json.return_value = {
            "base_resp": {"ret": 0},
            "articles": [{"title": "测试文章", "link": "fake_url", "create_time": 123456789}]
        }

        # 模拟下载正文 API 直接超时报错 (Exception)
        mock_get.side_effect = [
            mock_list_response,               # 第 1 次请求：获取文章列表 (成功)
            requests.exceptions.Timeout(),    # 第 2 次请求：下载正文 (超时报错)
            MagicMock(json=lambda: {"articles": []}) # 第 3 次请求：获取列表空了，触发结束机制
        ]

        # 屏蔽打印，防止测试日志太乱
        with patch('builtins.print'):
            scraper.fetch_pipeline()

        # 验证：程序没有崩溃，并且成功生成了 final 文件
        assert os.path.exists(scraper.FINAL_FILE)
        
        # 验证：那篇超时失败的文章，应该被保留，且 content 为空
        with open(scraper.FINAL_FILE, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["title"] == "测试文章"
            assert data[0]["content"] == ""