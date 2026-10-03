# S13 r2 原创建筑工厂场景

`model.py`保留纯Python核心语义/容量、搬运与FK；`layout.py`定义版本化坐标和候选比较；`usd_scene.py`构建原创USD；`inspection.py`执行原10路线及运动学实际读回；`trials.py`为T1—T4独立排演状态；`trial_scene.py`绑定真实USD与人员路径；`revision_checks.py`提供新专项及同口径负载测量。

入口为仓库根目录的`scripts/build_building_scene.py`和`scripts/view_building_scene.py`，使用既有Isaac环境，不自动获取第三方模型。场景是仓库资产，不包含在生产包wheel中。

原10个夹具是独立合成状态，切换会重置。T1—T4只在各自测试内部连续；切换测试同样明确RESET。核心局部坐标转世界坐标时加(14,4,0)，新厂界60×44 m。SCN对象不增加生产资源；质量UNKNOWN，HR禁用，没有DispatchCommand消费者或ExecutionEvent输出。

运行输出的scene.usda可用具名相机查看，外墙/屋顶/包络显示不改变碰撞API。详见[映射说明](../../../docs/sim/scene_mapping.md)、[试运行指南](../../../docs/sim/S13_trial_guide.md)和[37项工序覆盖](../../../docs/sim/S13_process_coverage.md)。
