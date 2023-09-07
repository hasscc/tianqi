# ☁️ 天气预报


本集成为HomeAssistant的中国用户提供天气实体(`weather`)，支持15天及逐小时预报、各种生活指数，兼容[彩云卡片](https://github.com/fineemb/lovelace-colorfulclouds-weather-card)，无需申请appkey。


> **Note**
> 
> 如果你想使用彩云卡片，请在配置集成时勾选`兼容彩云卡片`。
>
> 由于没有降水量及云层覆盖率数据，且彩云卡片需要这些数据，本集成提供的降水量及云层覆盖率是根据天气状况给的固定数据，仅供参考。


<a name="install"></a>
## 安装/更新

#### 方法1: [HACS (**点击这里安装**)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hasscc&repository=tianqi&category=integration)

#### 方法2: 通过 Samba / SFTP 手动安装
> [下载](https://github.com/hasscc/tianqi/archive/main.zip)解压并复制`custom_components/tianqi`文件夹到HA配置目录下的`custom_components`文件夹

#### 方法3: 通过`SSH`或`Terminal & SSH`加载项执行一键安装命令
```shell
wget -q -O - https://hacs.vip/get | HUB_DOMAIN=ghproxy.com/github.com DOMAIN=tianqi REPO_PATH=hasscc/tianqi ARCHIVE_TAG=main bash -
```

#### 方法4: `shell_command`服务
1. 复制代码到HA配置文件 `configuration.yaml`
    ```yaml
    shell_command:
      update_tianqi: |-
        wget -q -O - https://hacs.vip/get | HUB_DOMAIN=ghproxy.com/github.com DOMAIN=tianqi REPO_PATH=hasscc/tianqi ARCHIVE_TAG=main bash -
    ```
2. 重启HA
3. 在开发者工具中执行服务 [`service: shell_command.update_tianqi`](https://my.home-assistant.io/redirect/developer_call_service/?service=shell_command.update_tianqi)


<a name="config"></a>
## 配置

> [⚙️ 配置](https://my.home-assistant.io/redirect/config) > 设备与服务 > [🧩 集成](https://my.home-assistant.io/redirect/integrations) > [➕ 添加集成](https://my.home-assistant.io/redirect/config_flow_start?domain=tianqi) > 🔍 搜索 [`天气预报`](https://my.home-assistant.io/redirect/config_flow_start?domain=tianqi)


## 截图
<img width="800" alt="tianqi" src="https://github.com/hasscc/tianqi/assets/4549099/545e5c98-dce3-46b6-95c0-3e42d8a26a9a">

