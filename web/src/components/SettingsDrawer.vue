<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="open" class="settings-overlay" @keydown.esc="$emit('close')">
        <button class="settings-backdrop" type="button" aria-label="关闭设置" @click="$emit('close')"></button>
        <aside
          ref="settingsDrawerRef"
          class="settings-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Sierra 设置"
          @pointerdown.capture="playSettingsButtonPress"
          @pointerup.capture="playSettingsButtonRelease"
          @pointercancel.capture="playSettingsButtonRelease"
          @click.capture="playKeyboardButtonFeedback"
        >
          <nav class="settings-sidebar" aria-label="设置导航">
            <div class="settings-brand">
              <img src="/brand/sierra-avatar.png?v=transparent-1" alt="" />
              <span>
                <strong>Sierra</strong>
                <small>控制中心</small>
              </span>
            </div>

            <div class="settings-nav">
              <div v-for="group in sectionGroups" :key="group.label" class="settings-nav-group">
                <p>{{ group.label }}</p>
                <button
                  v-for="section in group.items"
                  :key="section.id"
                  :class="{ active: activeSection === section.id }"
                  type="button"
                  @click="activeSection = section.id"
                >
                  <component :is="section.icon" :size="16" />
                  <span>
                    <strong>{{ section.label }}</strong>
                    <small>{{ section.subtitle }}</small>
                  </span>
                  <b v-if="section.badge">{{ section.badge }}</b>
                </button>
              </div>
            </div>

            <div class="settings-sidebar-footer">
              <button type="button" @click="$emit('refresh')">刷新状态</button>
              <button type="button" @click="$emit('close')">关闭</button>
            </div>
          </nav>

          <main class="settings-main">
            <header class="settings-main-header">
              <div class="settings-main-title">
                <span>Settings</span>
                <h2>{{ activeSectionMeta.label }}</h2>
                <p>{{ activeSectionMeta.description }}</p>
              </div>
              <div class="settings-main-status" aria-label="当前状态">
                <span>
                  <small>模型</small>
                  <strong>{{ activeModelLabel }}</strong>
                </span>
                <span>
                  <small>上下文</small>
                  <strong>{{ usagePercent.toFixed(0) }}%</strong>
                </span>
              </div>
              <button class="icon-action" type="button" title="关闭" @click="$emit('close')">
                <X :size="18" />
              </button>
            </header>

            <div class="settings-content">
              <section v-if="activeSection === 'model'" class="settings-section">
                <div class="settings-page-toolbar">
                  <div>
                    <span>模型来源</span>
                    <h3>模型配置</h3>
                    <p>管理 Sierra 可以使用的模型。访问密钥只显示掩码，留空会保留原来的密钥。</p>
                  </div>
                  <div class="settings-actions">
                    <button type="button" @click="loadModelConfig">刷新</button>
                    <button type="button" :disabled="diagnosticsLoading === 'models'" @click="loadModelDiagnostics">
                      {{ diagnosticsLoading === "models" ? "诊断中" : "诊断" }}
                    </button>
                    <button type="button" @click="newModel">新增模型</button>
                  </div>
                </div>

                <div class="settings-kpi-grid">
                  <ListRow title="当前模型" :description="activeModelLabel" :meta="`${usagePercent.toFixed(0)}% 上下文`" />
                  <ListRow title="配置数量" :description="`${modelConfigs.length} 个模型配置`" :meta="activeModelConfig?.key || 'none'" />
                  <ListRow title="可用模型" :description="`${modelReadyCount} 个`" :meta="`${modelNeedsSetupCount} 待处理`" />
                  <ListRow title="视觉模型" :description="`${modelVisionCount} 个`" :meta="effectiveVisionEnabled ? '当前可看图' : '当前不可看图'" />
                </div>

                <div class="settings-config-layout model-config-layout">
                  <aside class="settings-list-pane config-index-panel">
                    <div class="config-panel-header">
                      <span>模型列表</span>
                      <b>{{ modelConfigs.length }}</b>
                    </div>
                    <button
                      v-for="model in modelConfigs"
                      :key="model.key"
                      class="config-list-item"
                      :class="{ selected: selectedModelKey === model.key }"
                      type="button"
                      @click="selectModel(model)"
                    >
                      <span class="config-list-main">
                        <strong>{{ model.key }}</strong>
                        <small>{{ model.name }} · {{ model.base_url || "未配置 base_url" }}</small>
                      </span>
                      <b :class="{ live: model.active, warn: modelDiagnostic(model.key)?.status === 'needs_setup' }">
                        {{ modelDiagnostic(model.key)?.status_label || (model.active ? "当前" : "编辑") }}
                      </b>
                    </button>
                    <ListRow v-if="!modelConfigs.length" title="没有模型" description="至少添加一个模型后才能对话。" />
                  </aside>

                  <section class="config-editor-panel">
                    <div class="config-editor-header">
                      <div>
                        <span>{{ selectedModelKey ? "编辑模型" : "新增模型" }}</span>
                        <h4>{{ modelForm.key || "未命名模型" }}</h4>
                      </div>
                      <div class="config-state-pills">
                        <b>{{ selectedModelIsActive ? "当前使用" : "可切换" }}</b>
                        <b :class="{ warn: selectedModelDiagnostic?.status === 'needs_setup' }">
                          {{ selectedModelDiagnostic?.status_label || "未诊断" }}
                        </b>
                        <b>{{ modelForm.context_window || 0 }} 上下文</b>
                      </div>
                    </div>

                    <form class="settings-editor config-editor-form" @submit.prevent="saveModel">
                      <div v-if="selectedModelDiagnostic" class="diagnostic-panel" :class="`status-${selectedModelDiagnostic.status}`">
                        <div>
                          <strong>{{ selectedModelDiagnostic.status_label }}</strong>
                          <span>{{ selectedModelDiagnostic.name }}</span>
                        </div>
                        <ul v-if="selectedModelDiagnostic.issues?.length">
                          <li v-for="issue in selectedModelDiagnostic.issues" :key="`${issue.path}-${issue.message}`">
                            <b>{{ issue.path }}</b>
                            <span>{{ issue.message }}</span>
                            <small v-if="issue.hint">{{ issue.hint }}</small>
                          </li>
                        </ul>
                        <p v-else>配置完整，Sierra 可以使用这个模型。</p>
                      </div>
                      <div class="settings-field-grid two">
                        <label>
                          <span>Key</span>
                          <input v-model.trim="modelForm.key" type="text" placeholder="deepseek" />
                        </label>
                        <label>
                          <span>模型名</span>
                          <input v-model.trim="modelForm.name" type="text" placeholder="deepseek-chat" />
                        </label>
                      </div>
                      <label>
                        <span>Base URL</span>
                        <input v-model.trim="modelForm.base_url" type="url" placeholder="https://api.example.com/v1" />
                      </label>
                      <label>
                        <span>访问密钥</span>
                        <input v-model="modelForm.api_key" type="password" :placeholder="modelApiPlaceholder" autocomplete="off" />
                      </label>
                      <div class="settings-editor-grid">
                        <label>
                          <span>输出上限</span>
                          <input v-model.number="modelForm.max_tokens" type="number" min="1" />
                        </label>
                        <label>
                          <span>温度</span>
                          <input v-model.number="modelForm.temperature" type="number" min="0" max="2" step="0.1" />
                        </label>
                        <label>
                          <span>上下文窗口</span>
                          <input v-model.number="modelForm.context_window" type="number" min="1" />
                        </label>
                      </div>
                      <div class="vision-status-card" :class="{ active: effectiveVisionEnabled }">
                        <span class="vision-status-orb" aria-hidden="true"></span>
                        <span>
                          <strong>{{ effectiveVisionEnabled ? "Sierra 当前可以看图" : "Sierra 当前不能看图" }}</strong>
                          <small>{{ visionStatusText }}</small>
                        </span>
                      </div>
                      <button
                        class="vision-toggle-button"
                        :class="{ active: modelForm.supports_vision }"
                        type="button"
                        :disabled="modelSaving"
                        :aria-pressed="modelForm.supports_vision"
                        @click.stop.prevent="toggleModelVision"
                      >
                        <span class="vision-toggle-track" aria-hidden="true">
                          <span class="vision-toggle-thumb"></span>
                        </span>
                        <span>
                          <strong>主模型原生视觉</strong>
                          <small>只有这个模型本身能看图时才开启；否则 Sierra 会使用上方的辅助视觉模块。</small>
                        </span>
                      </button>
                      <div class="settings-actions align-right">
                        <button type="submit" :disabled="modelSaving">
                          {{ modelSaving ? "保存中" : "保存配置" }}
                        </button>
                        <button v-if="modelForm.key" type="button" @click="switchModel(modelForm.key)">切换到此模型</button>
                        <button v-if="canDeleteModel" class="danger" type="button" @click="deleteModel(modelForm.key)">删除</button>
                      </div>
                    </form>
                  </section>
                </div>
                <p v-if="settingsNotice" class="settings-notice">{{ settingsNotice }}</p>
              </section>

              <section v-else-if="activeSection === 'skills'" class="settings-section">
                <div class="settings-page-toolbar">
                  <div>
                    <span>能力包</span>
                    <h3>Skills 管理</h3>
                    <p>参考 Hermes 的 Skills 页面：这里可以搜索、查看、编辑和新建本地 Skill。保存后 Sierra 会重新加载能力索引。</p>
                  </div>
                  <div class="settings-actions">
                    <button type="button" @click="newSkill">新建 Skill</button>
                    <button type="button" :disabled="skillReloading" @click="reloadSkills">
                      {{ skillReloading ? "加载中" : "重新加载" }}
                    </button>
                    <button type="button" :disabled="panelBusy === 'skills_stats'" @click="loadSkillStats">使用统计</button>
                  </div>
                </div>

                <PanelResult v-if="skillStatsText" title="使用统计" :text="skillStatsText" />
                <p v-if="skillNotice" class="settings-notice">{{ skillNotice }}</p>

                <div class="settings-kpi-grid">
                  <ListRow title="Skill 总数" :description="String(payload?.skills.count || 0)" />
                  <ListRow title="可提供" :description="String(skillOfferedCount)" :meta="`${skillErrors.length} 个错误`" />
                </div>

                <div class="settings-config-layout skill-config-layout">
                  <aside class="settings-list-pane config-index-panel">
                    <div class="config-panel-header">
                      <span>Skill 列表</span>
                      <b>{{ filteredSkills.length }}/{{ skills.length }}</b>
                    </div>
                    <input v-model="skillQuery" class="settings-list-search" type="text" placeholder="搜索 skill、分类或描述..." />
                    <button
                      v-for="skill in filteredSkills"
                      :key="skill.name"
                      class="config-list-item"
                      :class="{ selected: selectedSkillName === skill.name && skillEditorMode !== 'create' }"
                      type="button"
                      @click="selectSkill(skill.name)"
                    >
                      <span class="config-list-main">
                        <strong>{{ skill.name }}</strong>
                        <small>{{ skill.category || "general" }} · {{ skill.readiness_status || "ready" }}</small>
                      </span>
                      <b :class="{ live: skill.offered }">{{ skill.offered ? "可用" : "受限" }}</b>
                    </button>
                    <ListRow v-if="!filteredSkills.length" title="没有匹配的 Skill" description="换个关键词试试。" />
                  </aside>

                  <section class="config-editor-panel skill-editor-panel">
                    <div class="config-editor-header">
                      <div>
                        <span>{{ skillEditorMode === "create" ? "新建 Skill" : "编辑 Skill" }}</span>
                        <h4>{{ skillEditorTitle }}</h4>
                      </div>
                      <div class="config-state-pills">
                        <b>{{ selectedSkillDetail?.category || skillCreateCategory || "custom" }}</b>
                        <b>{{ selectedSkillDetail?.readiness_status || "draft" }}</b>
                      </div>
                    </div>

                    <div v-if="skillEditorMode === 'idle'" class="skill-empty-state">
                      <strong>选择一个 Skill 查看完整内容</strong>
                      <small>你也可以新建一个本地 Skill，让 Sierra 学会一套稳定的工作方法。</small>
                    </div>

                    <template v-else>
                      <div v-if="skillEditorMode === 'create'" class="settings-field-grid two">
                        <label>
                          <span>名称</span>
                          <input v-model.trim="skillCreateName" type="text" placeholder="my-skill" />
                        </label>
                        <label>
                          <span>分类</span>
                          <input v-model.trim="skillCreateCategory" type="text" placeholder="custom" />
                        </label>
                      </div>

                      <div v-if="selectedSkillDetail && skillEditorMode === 'edit'" class="skill-detail-summary">
                        <p>{{ selectedSkillDetail.description || "暂无描述" }}</p>
                        <span v-if="selectedSkillDetail.path">{{ selectedSkillDetail.path }}</span>
                      </div>

                      <textarea
                        v-model="skillEditorContent"
                        class="skill-content-editor"
                        spellcheck="false"
                        :disabled="skillEditorLoading || skillSaving"
                        placeholder="---&#10;name: my-skill&#10;description: When to use this skill.&#10;---&#10;&#10;# My Skill"
                      ></textarea>

                      <div class="settings-actions align-right">
                        <button type="button" :disabled="skillEditorLoading || skillSaving" @click="saveSkill">
                          {{ skillSaving ? "保存中" : "保存 Skill" }}
                        </button>
                        <button type="button" :disabled="skillSaving" @click="resetSkillEditor">取消</button>
                      </div>
                    </template>
                  </section>
                </div>

                <ListRow
                  v-for="errorItem in skillErrors"
                  :key="errorItem"
                  title="加载错误"
                  :description="errorItem"
                  meta="error"
                />
              </section>

              <section v-else-if="activeSection === 'mcp'" class="settings-section">
                <div class="settings-page-toolbar">
                  <div>
                    <span>工具接入</span>
                    <h3>MCP 配置</h3>
                    <p>连接本地或远程工具服务。保存后 Sierra 会重新读取可用工具。</p>
                  </div>
                  <div class="settings-actions">
                    <button type="button" @click="loadMcpConfig">刷新</button>
                    <button type="button" :disabled="diagnosticsLoading === 'mcp'" @click="loadMcpDiagnostics">
                      {{ diagnosticsLoading === "mcp" ? "诊断中" : "诊断" }}
                    </button>
                    <button type="button" @click="newMcp">新增 MCP</button>
                    <button type="button" :disabled="panelBusy === 'mcp'" @click="loadMcpStatus">运行状态</button>
                  </div>
                </div>

                <div class="settings-kpi-grid">
                  <ListRow title="服务数量" :description="`${mcpConfigs.length} 个工具服务`" :meta="`${enabledMcpCount} 已启用`" />
                  <ListRow title="当前编辑" :description="mcpForm.name || '新增工具服务'" :meta="mcpForm.type" />
                  <ListRow title="运行中" :description="`${mcpRunningCount} 个`" :meta="`${mcpNeedsSetupCount} 待处理`" />
                  <ListRow title="MCP 工具" :description="`${mcpToolCount} 个`" :meta="mcpDiagnostics?.summary?.tools ? '已发现' : '待发现'" />
                </div>
                <PanelResult v-if="mcpStatusText" title="运行状态" :text="mcpStatusText" />

                <div class="settings-config-layout mcp-config-layout">
                  <aside class="settings-list-pane config-index-panel">
                    <div class="config-panel-header">
                      <span>服务列表</span>
                      <b>{{ enabledMcpCount }}/{{ mcpConfigs.length }}</b>
                    </div>
                    <button
                      v-for="server in mcpConfigs"
                      :key="server.name"
                      class="config-list-item"
                      :class="{ selected: selectedMcpName === server.name }"
                      type="button"
                      @click="selectMcp(server)"
                    >
                      <span class="config-list-main">
                        <strong>{{ server.name }}</strong>
                        <small>{{ server.type }} · {{ server.url || server.command || "未配置入口" }}</small>
                      </span>
                      <b :class="{ live: mcpDiagnostic(server.name)?.status === 'running', warn: mcpDiagnostic(server.name)?.status === 'needs_setup' }">
                        {{ mcpDiagnostic(server.name)?.status_label || (server.enabled === false ? "off" : "on") }}
                      </b>
                    </button>
                    <ListRow v-if="!mcpConfigs.length" title="还没有工具服务" description="可以从右侧新增一个。" />
                  </aside>

                  <section class="config-editor-panel">
                    <div class="config-editor-header">
                      <div>
                        <span>{{ selectedMcpName ? "编辑服务" : "新增服务" }}</span>
                        <h4>{{ mcpForm.name || "未命名 MCP" }}</h4>
                      </div>
                      <div class="config-state-pills">
                        <b>{{ mcpForm.enabled ? "启用" : "停用" }}</b>
                        <b :class="{ warn: selectedMcpDiagnostic?.status === 'needs_setup' }">
                          {{ selectedMcpDiagnostic?.status_label || "未诊断" }}
                        </b>
                        <b>{{ mcpForm.type }}</b>
                      </div>
                    </div>

                    <form class="settings-editor config-editor-form" @submit.prevent="saveMcp">
                      <div v-if="selectedMcpDiagnostic" class="diagnostic-panel" :class="`status-${selectedMcpDiagnostic.status}`">
                        <div>
                          <strong>{{ selectedMcpDiagnostic.status_label }}</strong>
                          <span>{{ selectedMcpDiagnostic.transport }} · {{ selectedMcpDiagnostic.tools || 0 }} 个工具</span>
                        </div>
                        <ul v-if="selectedMcpDiagnostic.issues?.length">
                          <li v-for="issue in selectedMcpDiagnostic.issues" :key="`${issue.path}-${issue.message}`">
                            <b>{{ issue.path }}</b>
                            <span>{{ issue.message }}</span>
                            <small v-if="issue.hint">{{ issue.hint }}</small>
                          </li>
                        </ul>
                        <p v-else>配置没有发现明显问题。保存后 Sierra 会重新加载工具服务。</p>
                      </div>
                      <div class="settings-field-grid two">
                        <label>
                          <span>名称</span>
                          <input v-model.trim="mcpForm.name" type="text" placeholder="filesystem" />
                        </label>
                        <label class="settings-toggle mcp-enable-toggle">
                          <input v-model="mcpForm.enabled" type="checkbox" />
                          <span>启用这个工具服务</span>
                        </label>
                      </div>

                      <div class="mcp-transport-tabs" role="group" aria-label="MCP 传输方式">
                        <button
                          type="button"
                          :class="{ active: mcpForm.type === 'stdio' }"
                          @click="mcpForm.type = 'stdio'"
                        >
                          <strong>stdio</strong>
                          <small>本地启动的工具服务</small>
                        </button>
                        <button
                          type="button"
                          :class="{ active: mcpForm.type === 'streamablehttp' }"
                          @click="mcpForm.type = 'streamablehttp'"
                        >
                          <strong>streamablehttp</strong>
                          <small>远程网络工具服务</small>
                        </button>
                      </div>

                      <label v-if="mcpForm.type === 'streamablehttp'">
                        <span>URL</span>
                        <input v-model.trim="mcpForm.url" type="url" placeholder="https://example.com/mcp" />
                      </label>
                      <template v-else>
                        <div class="settings-field-grid two">
                          <label>
                            <span>Command</span>
                            <input v-model.trim="mcpForm.command" type="text" placeholder="python" />
                          </label>
                          <label>
                            <span>CWD</span>
                            <input v-model.trim="mcpForm.cwd" type="text" placeholder="可选" />
                          </label>
                        </div>
                        <label>
                          <span>Args</span>
                          <textarea v-model="mcpArgsText" rows="3" placeholder="每行一个参数"></textarea>
                        </label>
                        <label>
                          <span>Env JSON</span>
                          <textarea v-model="mcpEnvText" rows="5" spellcheck="false" placeholder="{ }"></textarea>
                        </label>
                      </template>
                      <label>
                        <span>Headers JSON</span>
                        <textarea v-model="mcpHeadersText" rows="5" spellcheck="false" placeholder="{ }"></textarea>
                      </label>
                      <div class="settings-actions align-right">
                        <button type="submit">保存并重载</button>
                        <button v-if="mcpForm.name" class="danger" type="button" @click="deleteMcp(mcpForm.name)">删除</button>
                      </div>
                    </form>
                  </section>
                </div>
                <p v-if="mcpNotice" class="settings-notice">{{ mcpNotice }}</p>
              </section>

              <section v-else-if="activeSection === 'safety'" class="settings-section">
                <SectionTitle title="安全" description="网页和终端都会遵守同一套安全规则，中高风险操作会先请求确认。" />
                <ListRow title="只读工具" description="读取、搜索、列目录等操作默认可直接运行。" meta="auto" />
                <ListRow title="写入 / 删除 / 终端" description="需要你确认后才会继续执行。" meta="confirm" />
                <button class="settings-row interactive" type="button" @click="openAuditPanel">
                  <span>
                    <strong>查看审计</strong>
                    <small>最近工具调用与权限记录</small>
                  </span>
                  <b>open</b>
                </button>
              </section>

              <section v-else-if="activeSection === 'tools'" class="settings-section">
                <div class="settings-page-toolbar">
                  <div>
                    <span>能力清单</span>
                    <h3>工具运行面板</h3>
                    <p>查看 Sierra 当前能调用的工具、权限策略和暴露方式。只读工具会直接运行，中高风险工具会先请求确认。</p>
                  </div>
                  <div class="settings-actions">
                    <button type="button" @click="$emit('refresh')">刷新</button>
                    <button type="button" :disabled="diagnosticsLoading === 'tools'" @click="loadToolDiagnostics">
                      {{ diagnosticsLoading === "tools" ? "诊断中" : "诊断" }}
                    </button>
                  </div>
                </div>

                <div class="settings-kpi-grid tools-kpi-grid">
                  <ListRow title="工具总数" :description="String(payload?.tools.total || 0)" />
                  <ListRow title="直接可见" :description="String(payload?.tools.direct || 0)" />
                  <ListRow title="延迟检索" :description="payload?.tools.tool_search_active ? '已启用' : '未启用'" :meta="`${payload?.tools.deferred || 0} 个`" />
                  <ListRow title="需要确认" :description="String(toolPermissionCount.ask || 0)" :meta="`${toolRiskCount.high || 0} 高风险`" />
                </div>
                <p v-if="toolNotice" class="settings-notice">{{ toolNotice }}</p>
                <div v-if="toolDiagnosticsView" class="tool-diagnostic-grid">
                  <article>
                    <span>权限策略</span>
                    <strong>{{ toolDiagnosticsView.summary?.permission?.ask || 0 }}</strong>
                    <small>需要确认的工具</small>
                  </article>
                  <article>
                    <span>高风险</span>
                    <strong>{{ toolDiagnosticsView.summary?.risk?.high || 0 }}</strong>
                    <small>写入、终端、外部动作</small>
                  </article>
                  <article>
                    <span>延迟暴露</span>
                    <strong>{{ toolDiagnosticsView.summary?.exposure?.deferred || 0 }}</strong>
                    <small>{{ toolDiagnosticsView.summary?.tool_search_active ? "tool_search 已启用" : "tool_search 未启用" }}</small>
                  </article>
                  <article>
                    <span>工具集</span>
                    <strong>{{ Object.keys(toolDiagnosticsView.summary?.toolsets || {}).length }}</strong>
                    <small>按能力域分组</small>
                  </article>
                </div>
                <div v-if="toolDiagnosticsView?.recommendations?.length" class="diagnostic-panel status-ready">
                  <div>
                    <strong>工具层建议</strong>
                    <span>根据当前注册表和权限策略生成</span>
                  </div>
                  <ul>
                    <li v-for="item in toolDiagnosticsView.recommendations" :key="item">
                      <span>{{ item }}</span>
                    </li>
                  </ul>
                </div>

                <div class="tool-control-strip">
                  <input v-model="toolQuery" type="text" placeholder="搜索工具、描述或工具集..." />
                  <select v-model="toolExposureFilter" aria-label="工具暴露方式">
                    <option value="all">全部方式</option>
                    <option value="direct">直接可见</option>
                    <option value="deferred">延迟检索</option>
                    <option value="bridge">检索桥接</option>
                  </select>
                  <select v-model="toolRiskFilter" aria-label="工具风险等级">
                    <option value="all">全部风险</option>
                    <option value="low">低风险</option>
                    <option value="medium">中风险</option>
                    <option value="high">高风险</option>
                    <option value="dynamic">动态判断</option>
                  </select>
                </div>

                <div class="toolset-cloud" aria-label="工具集分布">
                  <button
                    v-for="item in toolsets"
                    :key="item.name"
                    type="button"
                    :class="{ active: toolQuery === item.name }"
                    @click="toolQuery = toolQuery === item.name ? '' : item.name"
                  >
                    <span>{{ item.name }}</span>
                    <b>{{ item.count }}</b>
                  </button>
                </div>

                <div class="tool-catalog">
                  <article v-for="tool in filteredTools" :key="tool.name" class="tool-card" :class="`risk-${tool.risk || 'unknown'}`">
                    <div class="tool-card-main">
                      <span class="tool-card-icon">{{ tool.emoji || toolRiskIcon(tool.risk) }}</span>
                      <span>
                        <strong>{{ tool.name }}</strong>
                        <small>{{ tool.description || "暂无描述" }}</small>
                      </span>
                    </div>
                    <div class="tool-card-meta">
                      <b :class="`risk-${tool.risk || 'unknown'}`">{{ toolRiskLabel(tool.risk) }}</b>
                      <b>{{ toolPermissionLabel(tool.permission) }}</b>
                      <b>{{ toolExposureLabel(tool.exposure) }}</b>
                      <b>{{ tool.toolset || "core" }}</b>
                    </div>
                    <p v-if="tool.risk_reason" class="tool-risk-reason">{{ tool.risk_reason }}</p>
                  </article>
                  <ListRow v-if="!filteredTools.length" title="没有匹配的工具" description="换个关键词或清空筛选条件。" />
                </div>
              </section>

              <section v-else-if="activeSection === 'memory'" class="settings-section">
                <SectionTitle title="记忆" description="搜索长期记忆，查看记忆存储状态，或清理当前工作区的记忆。" />
                <div class="settings-form">
                  <input v-model="memoryQuery" type="text" placeholder="搜索记忆..." />
                  <button type="button" :disabled="panelBusy === 'memory_search'" @click="searchMemory">搜索</button>
                </div>
                <div class="settings-form">
                  <input v-model="forgetId" type="text" placeholder="记忆 ID" />
                  <button type="button" :disabled="panelBusy === 'memory_forget'" @click="forgetMemory">删除</button>
                  <button type="button" class="danger" :disabled="panelBusy === 'memory_clear'" @click="clearMemory">清空</button>
                </div>
                <PanelResult v-if="memoryCommandText" title="记忆结果" :text="memoryCommandText" />
                <div v-if="memorySearchResults.length" class="settings-result-list">
                  <ListRow
                    v-for="item in memorySearchResults"
                    :key="memoryResultKey(item)"
                    :title="memoryResultTitle(item)"
                    :description="memoryResultDescription(item)"
                    :meta="memoryResultMeta(item)"
                  />
                </div>
                <ListRow
                  v-for="provider in memoryProviders"
                  :key="provider.name"
                  :title="provider.name || 'provider'"
                  :description="provider.available === false ? provider.error || '不可用' : providerDescription(provider)"
                  :meta="provider.available === false ? 'off' : 'ready'"
                />
              </section>

              <section v-else-if="activeSection === 'task'" class="settings-section">
                <SectionTitle title="任务" description="查看当前计划，恢复中断任务，或放弃当前任务。" />
                <ListRow
                  v-if="currentTask"
                  :title="currentTask.objective || currentTask.id || '当前任务'"
                  :description="currentTask.status || 'unknown'"
                  :meta="taskProgress"
                />
                <ListRow v-else title="当前没有任务" description="Sierra 创建计划后会显示在这里。" />
                <div class="settings-actions">
                  <button type="button" :disabled="panelBusy === 'task'" @click="loadTaskStatus">查看任务</button>
                  <button v-if="recoveryTask" type="button" :disabled="panelBusy === 'task_resume'" @click="resumeTask">
                    恢复任务
                  </button>
                  <button v-if="currentTask" type="button" class="danger" :disabled="panelBusy === 'task_cancel'" @click="abandonTask">
                    放弃任务
                  </button>
                </div>
                <PanelResult v-if="taskCommandText" title="任务结果" :text="taskCommandText" />
              </section>

              <section v-else-if="activeSection === 'cron'" class="settings-section">
                <SectionTitle title="定时" description="创建和删除定时提示。网页和终端看到的是同一份提醒列表。" />
                <div class="settings-form">
                  <input v-model.number="cronMinutes" type="number" min="1" placeholder="分钟" />
                  <input v-model="cronPrompt" type="text" placeholder="提醒内容" />
                  <button type="button" :disabled="panelBusy === 'cron_add'" @click="addCron">创建</button>
                </div>
                <PanelResult v-if="cronNotice" title="定时结果" :text="cronNotice" />
                <button
                  v-for="task in cronTasks"
                  :key="task.id || task.name"
                  class="settings-row interactive"
                  type="button"
                  @click="removeCron(task)"
                >
                  <span>
                    <strong>{{ task.prompt || task.message || task.name || task.id }}</strong>
                    <small>every {{ task.interval_minutes || task.interval || "?" }} min · next {{ task.next_run_at || task.next || "pending" }}</small>
                  </span>
                  <b>delete</b>
                </button>
                <ListRow v-if="!cronTasks.length" title="暂无定时任务" description="创建提醒后会显示在这里。" />
              </section>

              <section v-else-if="activeSection === 'audit'" class="settings-section">
                <SectionTitle title="审计" description="最近工具调用和安全记录。" />
                <div class="settings-actions">
                  <button type="button" :disabled="panelBusy === 'audit'" @click="loadFullAudit">查看完整记录</button>
                </div>
                <PanelResult v-if="auditNotice" title="审计结果" :text="auditNotice" />
                <ListRow
                  v-for="record in displayedAuditRecords"
                  :key="`${record.timestamp}-${record.tool || record.name}`"
                  :title="record.tool || record.tool_name || record.name || 'tool'"
                  :description="record.timestamp || 'unknown time'"
                  :meta="record.success === false ? 'failed' : record.success === true ? 'ok' : record.risk || 'event'"
                />
                <ListRow v-if="!displayedAuditRecords.length" title="暂无审计记录" description="调用工具后会显示。" />
              </section>

              <section v-else-if="activeSection === 'integrations'" class="settings-section">
                <div class="settings-page-toolbar">
                  <div>
                    <span>聊天入口</span>
                    <h3>平台接入</h3>
                    <p>把 Sierra 接到不同聊天入口。当前先保证 Web 体验稳定，其他平台后续通过令牌、回调地址和消息路由启用。</p>
                  </div>
                </div>

                <div class="integration-summary">
                  <div>
                    <small>当前可用入口</small>
                    <strong>Web</strong>
                    <span>支持聊天、工具确认、用户补充输入、模型与 MCP 配置。</span>
                  </div>
                  <div>
                    <small>下一阶段</small>
                    <strong>回调接入</strong>
                    <span>为 Telegram、飞书、微信等平台准备统一的消息入口。</span>
                  </div>
                </div>

                <div class="integration-grid">
                  <article
                    v-for="channel in integrationChannels"
                    :key="channel.name"
                    class="integration-card"
                    :class="channel.status"
                  >
                    <div class="integration-card-head">
                      <span>{{ channel.icon }}</span>
                      <b>{{ channel.badge }}</b>
                    </div>
                    <h4>{{ channel.name }}</h4>
                    <p>{{ channel.description }}</p>
                    <small>{{ channel.next }}</small>
                  </article>
                </div>
              </section>

              <section v-else class="settings-section">
                <SectionTitle title="关于" description="Sierra 网页控制台" />
                <ListRow title="版本" description="0.1.0" />
              </section>
            </div>
          </main>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import {
  BrainCircuit,
  CalendarClock,
  Database,
  KeyRound,
  Network,
  ScrollText,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  WandSparkles,
  Wrench,
  X
} from "lucide-vue-next";
import { gsap } from "gsap";
import { computed, defineComponent, h, ref, watch } from "vue";
import type { Component } from "vue";
import type { DashboardPayload } from "../types";

type SettingsSection =
  | "model"
  | "skills"
  | "mcp"
  | "tools"
  | "safety"
  | "memory"
  | "task"
  | "cron"
  | "audit"
  | "integrations"
  | "about";

type SettingsSectionMeta = {
  id: SettingsSection;
  label: string;
  subtitle: string;
  description: string;
  group: "核心配置" | "能力扩展" | "运行维护" | "系统";
  icon: Component;
  badge?: string;
};

const props = defineProps<{
  activeModelLabel: string;
  open: boolean;
  payload: DashboardPayload | null;
  usagePercent: number;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "refresh"): void;
}>();

const activeSection = ref<SettingsSection>("model");
const settingsDrawerRef = ref<HTMLElement | null>(null);
const cronMinutes = ref(60);
const cronPrompt = ref("");
const memoryQuery = ref("");
const forgetId = ref("");
const skillQuery = ref("");
const selectedSkillName = ref("");
const selectedSkillDetail = ref<any | null>(null);
const skillEditorMode = ref<"idle" | "edit" | "create">("idle");
const skillEditorContent = ref("");
const skillEditorLoading = ref(false);
const skillSaving = ref(false);
const skillNotice = ref("");
const skillCreateName = ref("");
const skillCreateCategory = ref("custom");
const toolQuery = ref("");
const toolExposureFilter = ref("all");
const toolRiskFilter = ref("all");
const skillReloading = ref(false);
const settingsNotice = ref("");
const mcpNotice = ref("");
const toolNotice = ref("");
const diagnosticsLoading = ref("");
const panelBusy = ref("");
const modelSaving = ref(false);
const skillStatsText = ref("");
const mcpStatusText = ref("");
const memoryCommandText = ref("");
const memorySearchResults = ref<any[]>([]);
const auditPanelRecords = ref<any[]>([]);
const auditNotice = ref("");
const taskCommandText = ref("");
const cronNotice = ref("");

const modelConfigs = ref<any[]>([]);
const modelDiagnostics = ref<any | null>(null);
const selectedModelKey = ref("");
const modelForm = ref({
  key: "",
  name: "",
  base_url: "",
  api_key: "",
  max_tokens: 4096,
  temperature: 0.7,
  context_window: 256000,
  supports_vision: false
});

const mcpConfigs = ref<any[]>([]);
const mcpDiagnostics = ref<any | null>(null);
const selectedMcpName = ref("");
const mcpForm = ref({
  name: "",
  type: "stdio",
  command: "",
  args: [] as string[],
  url: "",
  cwd: "",
  enabled: true
});
const mcpArgsText = ref("");
const mcpHeadersText = ref("{}");
const mcpEnvText = ref("{}");
const toolDiagnosticsOverride = ref<any | null>(null);

const NEW_SKILL_TEMPLATE = `---
name: my-skill
description: Describe when Sierra should use this skill.
---

# My Skill

Write the stable workflow here:

1. When to use this skill.
2. What Sierra should check first.
3. Exact steps, commands, examples, and pitfalls.
`;

const sections: SettingsSectionMeta[] = [
  {
    id: "model",
    label: "模型",
    subtitle: "提供商与参数",
    description: "管理可用模型、切换当前模型，并维护兼容接口的连接信息。",
    group: "核心配置",
    icon: SlidersHorizontal
  },
  {
    id: "skills",
    label: "Skills",
    subtitle: "能力包索引",
    description: "查看 Sierra 可以按任务调用的能力包，搜索能力并刷新列表。",
    group: "能力扩展",
    icon: WandSparkles
  },
  {
    id: "mcp",
    label: "MCP",
    subtitle: "外部工具接入",
    description: "新增、编辑、删除外部工具服务。保存后 Sierra 会重新读取可用工具。",
    group: "能力扩展",
    icon: Network
  },
  {
    id: "tools",
    label: "工具",
    subtitle: "能力概览",
    description: "查看 Sierra 当前能使用的工具，以及按用途划分的工具分类。",
    group: "能力扩展",
    icon: Wrench
  },
  {
    id: "safety",
    label: "安全",
    subtitle: "权限与确认",
    description: "查看工具安全规则。涉及写入、删除或终端操作时会先请求确认。",
    group: "核心配置",
    icon: ShieldCheck
  },
  {
    id: "memory",
    label: "记忆",
    subtitle: "长期上下文",
    description: "搜索长期记忆、查看记忆存储状态，或管理当前工作区记忆。",
    group: "核心配置",
    icon: Database
  },
  {
    id: "task",
    label: "任务",
    subtitle: "计划与恢复",
    description: "查看当前任务计划，恢复中断任务，或放弃不再需要的任务。",
    group: "运行维护",
    icon: BrainCircuit
  },
  {
    id: "cron",
    label: "定时",
    subtitle: "提醒任务",
    description: "创建和删除定时提示。网页和终端会看到同一份提醒列表。",
    group: "运行维护",
    icon: CalendarClock
  },
  {
    id: "audit",
    label: "审计",
    subtitle: "工具调用记录",
    description: "查看最近工具调用、权限确认与安全审计记录。",
    group: "运行维护",
    icon: ScrollText
  },
  {
    id: "integrations",
    label: "平台",
    subtitle: "聊天入口",
    description: "查看 Web、Telegram、飞书、微信等入口的接入状态和下一步准备事项。",
    group: "系统",
    icon: KeyRound
  },
  {
    id: "about",
    label: "关于",
    subtitle: "版本信息",
    description: "查看 Sierra 网页控制台的版本和基础信息。",
    group: "系统",
    icon: Settings2
  }
];

const activeSectionMeta = computed(() => {
  return sections.find((section) => section.id === activeSection.value) || sections[0];
});

const sectionGroups = computed(() => {
  const order: SettingsSectionMeta["group"][] = ["核心配置", "能力扩展", "运行维护", "系统"];
  return order
    .map((label) => ({
      label,
      items: sections.filter((section) => section.group === label)
    }))
    .filter((group) => group.items.length);
});

const models = computed(() => Array.isArray(props.payload?.identity.models) ? props.payload?.identity.models : []);
const skills = computed(() => Array.isArray(props.payload?.skills?.items) ? props.payload?.skills?.items : []);
const skillErrors = computed(() => Array.isArray(props.payload?.skills?.errors) ? props.payload?.skills?.errors : []);
const skillOfferedCount = computed(() => skills.value.filter((skill: any) => skill.offered).length);
const skillEditorTitle = computed(() => {
  if (skillEditorMode.value === "create") {
    return skillCreateName.value || "未命名 Skill";
  }
  return selectedSkillName.value || "未选择 Skill";
});
const filteredSkills = computed(() => {
  const query = skillQuery.value.trim().toLowerCase();
  if (!query) {
    return skills.value;
  }
  return skills.value.filter((skill: any) => {
    return [skill.name, skill.category, skill.description, skill.readiness_status]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });
});
const memoryProviders = computed(() => {
  return Array.isArray(props.payload?.memory?.providers) ? props.payload?.memory?.providers : [];
});
const currentTask = computed(() => props.payload?.tasks?.current || null);
const recoveryTask = computed(() => props.payload?.tasks?.recovery || null);
const taskProgress = computed(() => {
  const steps = Array.isArray(currentTask.value?.steps) ? currentTask.value.steps : [];
  if (!steps.length) {
    return "";
  }
  const done = steps.filter((step: any) => step.status === "completed").length;
  return `${done}/${steps.length}`;
});
const cronTasks = computed(() => {
  return Array.isArray(props.payload?.cron?.tasks) ? props.payload?.cron?.tasks : [];
});
const auditRecords = computed(() => {
  return Array.isArray(props.payload?.audit?.records) ? props.payload?.audit?.records : [];
});
const displayedAuditRecords = computed(() => {
  return auditPanelRecords.value.length ? auditPanelRecords.value : auditRecords.value;
});
const toolsets = computed(() => {
  const raw = props.payload?.tools?.toolsets || {};
  return Object.entries(raw).map(([name, count]) => ({ name, count }));
});
const tools = computed(() => {
  return Array.isArray(props.payload?.tools?.items) ? props.payload?.tools?.items : [];
});
const filteredTools = computed(() => {
  const query = toolQuery.value.trim().toLowerCase();
  return tools.value.filter((tool: any) => {
    const exposure = String(tool?.exposure || "direct");
    const risk = String(tool?.risk || "unknown");
    if (toolExposureFilter.value !== "all" && exposure !== toolExposureFilter.value) {
      return false;
    }
    if (toolRiskFilter.value !== "all" && risk !== toolRiskFilter.value) {
      return false;
    }
    if (!query) {
      return true;
    }
    return [
      tool?.name,
      tool?.description,
      tool?.toolset,
      tool?.risk,
      tool?.permission,
      tool?.exposure
    ].some((value) => String(value || "").toLowerCase().includes(query));
  });
});
const toolRiskCount = computed(() => {
  return tools.value.reduce((acc: Record<string, number>, tool: any) => {
    const risk = String(tool?.risk || "unknown");
    acc[risk] = (acc[risk] || 0) + 1;
    return acc;
  }, {});
});
const toolPermissionCount = computed(() => {
  return tools.value.reduce((acc: Record<string, number>, tool: any) => {
    const permission = String(tool?.permission || "unknown");
    acc[permission] = (acc[permission] || 0) + 1;
    return acc;
  }, {});
});
const activeModelConfig = computed(() => modelConfigs.value.find((item) => item.active) || null);
const selectedModelIsActive = computed(() => {
  return Boolean(modelForm.value.key) && activeModelConfig.value?.key === modelForm.value.key;
});
const modelDiagnosticsItems = computed(() => {
  return Array.isArray(modelDiagnostics.value?.items) ? modelDiagnostics.value.items : [];
});
const selectedModelDiagnostic = computed(() => modelDiagnostic(modelForm.value.key));
const modelReadyCount = computed(() => modelDiagnosticsItems.value.filter((item: any) => ["active", "ready"].includes(String(item?.status))).length);
const modelNeedsSetupCount = computed(() => modelDiagnosticsItems.value.filter((item: any) => ["needs_setup", "invalid"].includes(String(item?.status))).length);
const modelVisionCount = computed(() => Number(modelDiagnostics.value?.summary?.vision_models || 0));
const capabilityItems = computed(() => {
  const unified = props.payload?.capabilities?.items;
  if (Array.isArray(unified)) {
    return unified;
  }
  const legacy = props.payload?.auxiliary?.capabilities;
  return Array.isArray(legacy) ? legacy : [];
});
const visionCapability = computed(() => {
  return capabilityItems.value.find((item: any) => String(item?.name || "").toLowerCase() === "vision") || null;
});
const auxiliaryVisionEnabled = computed(() => Boolean(visionCapability.value?.enabled));
const effectiveVisionEnabled = computed(() => Boolean(modelForm.value.supports_vision || auxiliaryVisionEnabled.value));
const visionStatusText = computed(() => {
  if (modelForm.value.supports_vision) {
    return "当前选中的主模型被标记为可直接分析图片。";
  }
  if (auxiliaryVisionEnabled.value) {
    const model = String(visionCapability.value?.model || "辅助视觉模型");
    const route = String(visionCapability.value?.route || visionCapability.value?.provider || "auxiliary");
    return `辅助视觉已启用，将通过 ${model} 处理图片。路由: ${route}`;
  }
  return "请在 config.json 的 auxiliary.vision 中启用辅助视觉，或把真正的多模态主模型标记为原生视觉。";
});
const enabledMcpCount = computed(() => mcpConfigs.value.filter((server) => server.enabled !== false).length);
const mcpDiagnosticsItems = computed(() => {
  return Array.isArray(mcpDiagnostics.value?.items) ? mcpDiagnostics.value.items : [];
});
const selectedMcpDiagnostic = computed(() => mcpDiagnostic(mcpForm.value.name));
const mcpRunningCount = computed(() => Number(mcpDiagnostics.value?.summary?.running || 0));
const mcpNeedsSetupCount = computed(() => mcpDiagnosticsItems.value.filter((item: any) => ["needs_setup", "failed", "invalid"].includes(String(item?.status))).length);
const mcpToolCount = computed(() => Number(mcpDiagnostics.value?.summary?.tools || 0));
const toolDiagnosticsView = computed(() => toolDiagnosticsOverride.value || props.payload?.tools?.diagnostics || null);
const integrationChannels = [
  {
    name: "Web",
    icon: "🌿",
    badge: "已启用",
    status: "ready",
    description: "浏览器聊天入口，支持连续对话、工具确认、文件上传和设置管理。",
    next: "当前推荐使用入口。"
  },
  {
    name: "开放接口",
    icon: "🔗",
    badge: "可扩展",
    status: "ready",
    description: "Sierra 已经具备聊天、命令、审批、配置等基础能力，可作为外部平台接入入口。",
    next: "下一步可以补登录鉴权和访问控制。"
  },
  {
    name: "Telegram",
    icon: "✈",
    badge: "待配置",
    status: "planned",
    description: "适合个人随身聊天和轻量通知，需要机器人令牌与回调地址。",
    next: "准备令牌、消息路由和工具确认交互。"
  },
  {
    name: "飞书",
    icon: "💬",
    badge: "待配置",
    status: "planned",
    description: "适合团队通知、任务协作和工作流入口，需要应用凭证与事件订阅。",
    next: "准备应用凭证、回调校验和消息卡片。"
  },
  {
    name: "微信",
    icon: "🍃",
    badge: "计划中",
    status: "later",
    description: "适合作为日常陪伴入口，接入方式取决于公众号、企微或个人协议方案。",
    next: "先确定合规接入方式，再设计消息同步。"
  },
  {
    name: "QQ",
    icon: "✨",
    badge: "计划中",
    status: "later",
    description: "适合社群或个人聊天场景，后续可作为独立适配器接入。",
    next: "等回调入口稳定后再接入。"
  }
];
const modelApiPlaceholder = computed(() => {
  const selected = modelConfigs.value.find((item) => item.key === selectedModelKey.value);
  return selected?.api_key_set ? `已设置 ${selected.api_key_preview || "********"}，留空保留` : "sk-...";
});
const canDeleteModel = computed(() => {
  return Boolean(modelForm.value.key) && modelConfigs.value.length > 1 && !modelConfigs.value.find((item) => item.key === modelForm.value.key)?.active;
});

watch(
  () => props.open,
  (open) => {
    if (open) {
      loadModelConfig();
      loadMcpConfig();
    }
  },
  { immediate: true }
);

watch(models, () => {
  if (!modelConfigs.value.length) {
    modelConfigs.value = models.value.map((model: any) => ({ ...model }));
  }
});

async function runPanelCommand(command: string | Record<string, any>, options: { refresh?: boolean } = {}) {
  const rawBody = typeof command === "string"
    ? { command: command.trim().split(/\s+/)[0] || "/help", text: command }
    : { ...command };
  const body: Record<string, any> = {
    ...rawBody,
    command: String(rawBody.command || rawBody.text || "/help").trim().split(/\s+/)[0] || "/help"
  };
  const busyKey = String(body.command || "").replace(/^\//, "").replace(/-/g, "_");
  panelBusy.value = busyKey;
  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Command API ${response.status}`);
    }
    if (data.requires_confirmation) {
      const confirmed = window.confirm(String(data.text || "确认执行这个操作？"));
      if (!confirmed) {
        return { ok: false, type: "cancelled", text: "已取消操作。" };
      }
      return await runPanelCommand({ ...body, confirmed: true }, options);
    }
    if (options.refresh !== false) {
      emit("refresh");
    }
    return data;
  } catch (err) {
    return {
      ok: false,
      type: "error",
      text: `操作失败: ${err instanceof Error ? err.message : String(err)}`
    };
  } finally {
    panelBusy.value = "";
  }
}

async function loadModelConfig() {
  try {
    const response = await fetch("/api/config/models");
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `Model config API ${response.status}`);
    }
    modelConfigs.value = Array.isArray(data.models) ? data.models : [];
    modelDiagnostics.value = data.diagnostics || null;
    if (!selectedModelKey.value && modelConfigs.value.length) {
      selectModel(modelConfigs.value.find((model) => model.active) || modelConfigs.value[0]);
    } else if (selectedModelKey.value) {
      const selected = modelConfigs.value.find((model) => model.key === selectedModelKey.value);
      if (selected) {
        selectModel(selected);
      }
    }
  } catch (err) {
    settingsNotice.value = `加载模型配置失败: ${err instanceof Error ? err.message : String(err)}`;
  }
}

async function loadModelDiagnostics() {
  diagnosticsLoading.value = "models";
  settingsNotice.value = "";
  try {
    const response = await fetch("/api/config/models/diagnostics");
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `Model diagnostics API ${response.status}`);
    }
    modelDiagnostics.value = data.diagnostics || null;
    settingsNotice.value = "模型诊断已更新。";
  } catch (err) {
    settingsNotice.value = `模型诊断失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    diagnosticsLoading.value = "";
  }
}

function modelDiagnostic(key: any) {
  const normalized = String(key || "");
  return modelDiagnosticsItems.value.find((item: any) => String(item?.key || "") === normalized) || null;
}

function selectModel(model: any) {
  selectedModelKey.value = String(model.key || "");
  modelForm.value = {
    key: String(model.key || ""),
    name: String(model.name || ""),
    base_url: String(model.base_url || ""),
    api_key: "",
    max_tokens: Number(model.max_tokens || 4096),
    temperature: Number(model.temperature ?? 0.7),
    context_window: Number(model.context_window || 256000),
    supports_vision: Boolean(model.supports_vision)
  };
  settingsNotice.value = "";
}

function newModel() {
  selectedModelKey.value = "";
  modelForm.value = {
    key: "",
    name: "",
    base_url: "",
    api_key: "",
    max_tokens: 4096,
    temperature: 0.7,
    context_window: 256000,
    supports_vision: false
  };
  settingsNotice.value = "";
}

async function toggleModelVision() {
  const previous = modelForm.value.supports_vision;
  modelForm.value.supports_vision = !previous;
  settingsNotice.value = "";
  const isExistingModel = modelConfigs.value.some((model) => model.key === modelForm.value.key);
  if (!isExistingModel) {
    return;
  }
  const ok = await saveModel({
    pendingText: modelForm.value.supports_vision
      ? "正在启用图片理解，并热重载 Sierra..."
      : "正在关闭图片理解，并热重载 Sierra..."
  });
  if (!ok) {
    modelForm.value.supports_vision = previous;
  }
}

function playSettingsButtonPress(event: PointerEvent) {
  const target = feedbackButtonFromEvent(event);
  if (!target || prefersReducedMotion()) {
    return;
  }
  gsap.killTweensOf(target);
  gsap.to(target, {
    scale: 0.965,
    duration: 0.08,
    ease: "power2.out",
    overwrite: "auto"
  });
}

function playSettingsButtonRelease(event: PointerEvent) {
  const target = feedbackButtonFromEvent(event);
  if (!target || prefersReducedMotion()) {
    return;
  }
  gsap.to(target, {
    scale: 1,
    duration: 0.34,
    ease: "back.out(2.6)",
    clearProps: "transform",
    overwrite: "auto"
  });
}

function playKeyboardButtonFeedback(event: MouseEvent) {
  if (event.detail !== 0) {
    return;
  }
  const target = feedbackButtonFromEvent(event);
  if (!target || prefersReducedMotion()) {
    return;
  }
  gsap.fromTo(
    target,
    { scale: 0.97 },
    {
      scale: 1,
      duration: 0.32,
      ease: "back.out(2.4)",
      clearProps: "transform",
      overwrite: "auto"
    }
  );
}

function feedbackButtonFromEvent(event: Event) {
  const rawTarget = event.target;
  if (!(rawTarget instanceof Element)) {
    return null;
  }
  const button = rawTarget.closest("button");
  if (!(button instanceof HTMLElement) || button.disabled || button.classList.contains("settings-backdrop")) {
    return null;
  }
  return button;
}

function prefersReducedMotion() {
  return typeof window !== "undefined"
    && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

async function saveModel(options: { pendingText?: string } | Event = {}) {
  if (modelSaving.value) {
    return false;
  }
  modelSaving.value = true;
  const pendingText = options instanceof Event ? "" : options.pendingText || "";
  settingsNotice.value = pendingText;
  try {
    const response = await fetch("/api/config/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(modelForm.value)
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `Model config API ${response.status}`);
    }
    settingsNotice.value = data.text || "模型配置已保存。";
    modelConfigs.value = Array.isArray(data.models) ? data.models : modelConfigs.value;
    modelDiagnostics.value = data.diagnostics || modelDiagnostics.value;
    const savedKey = modelForm.value.key;
    const savedModel = modelConfigs.value.find((model) => model.key === savedKey);
    if (savedModel) {
      selectModel(savedModel);
    } else {
      selectedModelKey.value = savedKey;
      modelForm.value.api_key = "";
    }
    settingsNotice.value = data.text || "模型配置已保存。";
    emit("refresh");
    return true;
  } catch (err) {
    settingsNotice.value = `保存失败: ${err instanceof Error ? err.message : String(err)}`;
    return false;
  } finally {
    modelSaving.value = false;
  }
}

async function switchModel(key: string) {
  if (!key) {
    return;
  }
  settingsNotice.value = "";
  const data = await runPanelCommand({ command: "model", key, text: `/model ${key}` });
  settingsNotice.value = data.text || "模型已切换。";
  await loadModelConfig();
}

async function deleteModel(key: string) {
  if (!key || !window.confirm(`确认删除模型配置 ${key}？`)) {
    return;
  }
  try {
    const response = await fetch(`/api/config/models/${encodeURIComponent(key)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `Model config API ${response.status}`);
    }
    settingsNotice.value = data.text || "模型配置已删除。";
    modelConfigs.value = Array.isArray(data.models) ? data.models : [];
    modelDiagnostics.value = data.diagnostics || modelDiagnostics.value;
    newModel();
    emit("refresh");
  } catch (err) {
    settingsNotice.value = `删除失败: ${err instanceof Error ? err.message : String(err)}`;
  }
}

async function reloadSkills() {
  skillReloading.value = true;
  skillNotice.value = "";
  try {
    const response = await fetch("/api/skills/reload", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `Skills API ${response.status}`);
    }
    const notice = data.text || "Skill 索引已重新加载。";
    emit("refresh");
    if (selectedSkillName.value && skillEditorMode.value === "edit") {
      await selectSkill(selectedSkillName.value);
    }
    skillNotice.value = notice;
  } catch (err) {
    skillNotice.value = `重新加载 Skill 失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    skillReloading.value = false;
  }
}

async function selectSkill(name: string) {
  if (!name) {
    return;
  }
  selectedSkillName.value = name;
  selectedSkillDetail.value = null;
  skillEditorMode.value = "edit";
  skillEditorLoading.value = true;
  skillNotice.value = "";
  try {
    const response = await fetch(`/api/skills/${encodeURIComponent(name)}`);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.detail || data.text || data.error || `Skill API ${response.status}`);
    }
    selectedSkillDetail.value = data.skill || null;
    skillEditorContent.value = String(data.content || "");
  } catch (err) {
    skillNotice.value = `读取 Skill 失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    skillEditorLoading.value = false;
  }
}

function newSkill() {
  selectedSkillName.value = "";
  selectedSkillDetail.value = null;
  skillEditorMode.value = "create";
  skillEditorContent.value = NEW_SKILL_TEMPLATE;
  skillCreateName.value = "";
  skillCreateCategory.value = "custom";
  skillNotice.value = "";
}

function resetSkillEditor() {
  selectedSkillName.value = "";
  selectedSkillDetail.value = null;
  skillEditorMode.value = "idle";
  skillEditorContent.value = "";
  skillCreateName.value = "";
  skillCreateCategory.value = "custom";
  skillNotice.value = "";
}

function skillContentWithName(content: string, name: string) {
  const cleanName = name.trim();
  if (!cleanName) {
    return content;
  }
  if (/(\r?\nname:\s*)[^\r\n]+/.test(content)) {
    return content.replace(/(\r?\nname:\s*)[^\r\n]+/, (_match, prefix) => `${prefix}${cleanName}`);
  }
  if (/^---\s*\r?\n/.test(content)) {
    return content.replace(/^---\s*\r?\n/, `---\nname: ${cleanName}\n`);
  }
  return content;
}

async function saveSkill() {
  if (skillSaving.value) {
    return;
  }
  skillNotice.value = "";
  skillSaving.value = true;
  try {
    const creating = skillEditorMode.value === "create";
    const endpoint = creating
      ? "/api/skills"
      : `/api/skills/${encodeURIComponent(selectedSkillName.value)}`;
    const content = creating
      ? skillContentWithName(skillEditorContent.value, skillCreateName.value.trim())
      : skillEditorContent.value;
    if (creating) {
      skillEditorContent.value = content;
    }
    const body = creating
      ? {
          name: skillCreateName.value.trim(),
          category: skillCreateCategory.value.trim() || "custom",
          content
        }
      : { content };
    const response = await fetch(endpoint, {
      method: creating ? "POST" : "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.detail || data.text || data.error || `Skill API ${response.status}`);
    }
    const savedName = String(data.name || skillCreateName.value || selectedSkillName.value);
    const notice = data.text || "Skill 已保存。";
    emit("refresh");
    if (savedName) {
      await selectSkill(savedName);
    }
    skillNotice.value = notice;
  } catch (err) {
    skillNotice.value = `保存 Skill 失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    skillSaving.value = false;
  }
}

async function loadMcpConfig() {
  try {
    const response = await fetch("/api/config/mcp");
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `MCP config API ${response.status}`);
    }
    mcpConfigs.value = Array.isArray(data.servers) ? data.servers : [];
    mcpDiagnostics.value = data.diagnostics || null;
    if (!selectedMcpName.value && mcpConfigs.value.length) {
      selectMcp(mcpConfigs.value[0]);
    } else if (selectedMcpName.value) {
      const selected = mcpConfigs.value.find((server) => server.name === selectedMcpName.value);
      if (selected) {
        selectMcp(selected);
      }
    }
  } catch (err) {
    mcpNotice.value = `加载 MCP 配置失败: ${err instanceof Error ? err.message : String(err)}`;
  }
}

async function loadMcpDiagnostics() {
  diagnosticsLoading.value = "mcp";
  mcpNotice.value = "";
  try {
    const response = await fetch("/api/config/mcp/diagnostics");
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `MCP diagnostics API ${response.status}`);
    }
    mcpDiagnostics.value = data.diagnostics || null;
    mcpNotice.value = "MCP 诊断已更新。";
  } catch (err) {
    mcpNotice.value = `MCP 诊断失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    diagnosticsLoading.value = "";
  }
}

function mcpDiagnostic(name: any) {
  const normalized = String(name || "");
  return mcpDiagnosticsItems.value.find((item: any) => String(item?.name || "") === normalized) || null;
}

function selectMcp(server: any) {
  selectedMcpName.value = String(server.name || "");
  mcpForm.value = {
    name: String(server.name || ""),
    type: String(server.type || "stdio"),
    command: String(server.command || ""),
    args: Array.isArray(server.args) ? server.args : [],
    url: String(server.url || ""),
    cwd: String(server.cwd || ""),
    enabled: server.enabled !== false
  };
  mcpArgsText.value = Array.isArray(server.args) ? server.args.join("\n") : "";
  mcpHeadersText.value = formatJson(server.headers || {});
  mcpEnvText.value = formatJson(server.env || {});
  mcpNotice.value = "";
}

function newMcp() {
  selectedMcpName.value = "";
  mcpForm.value = {
    name: "",
    type: "stdio",
    command: "",
    args: [],
    url: "",
    cwd: "",
    enabled: true
  };
  mcpArgsText.value = "";
  mcpHeadersText.value = "{}";
  mcpEnvText.value = "{}";
  mcpNotice.value = "";
}

async function saveMcp() {
  mcpNotice.value = "";
  try {
    const headers = parseJsonObject(mcpHeadersText.value, "Headers JSON");
    const env = parseJsonObject(mcpEnvText.value, "Env JSON");
    const args = mcpArgsText.value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    const body = {
      ...mcpForm.value,
      args,
      headers,
      env
    };
    const response = await fetch("/api/config/mcp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `MCP config API ${response.status}`);
    }
    mcpNotice.value = data.text || "MCP 配置已保存。";
    mcpConfigs.value = Array.isArray(data.servers) ? data.servers : mcpConfigs.value;
    mcpDiagnostics.value = data.diagnostics || mcpDiagnostics.value;
    selectedMcpName.value = mcpForm.value.name;
    emit("refresh");
  } catch (err) {
    mcpNotice.value = `保存失败: ${err instanceof Error ? err.message : String(err)}`;
  }
}

async function deleteMcp(name: string) {
  if (!name || !window.confirm(`确认删除工具服务 ${name}？`)) {
    return;
  }
  try {
    const response = await fetch(`/api/config/mcp/${encodeURIComponent(name)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `MCP config API ${response.status}`);
    }
    mcpNotice.value = data.text || "MCP 配置已删除。";
    mcpConfigs.value = Array.isArray(data.servers) ? data.servers : [];
    mcpDiagnostics.value = data.diagnostics || mcpDiagnostics.value;
    newMcp();
    emit("refresh");
  } catch (err) {
    mcpNotice.value = `删除失败: ${err instanceof Error ? err.message : String(err)}`;
  }
}

function parseJsonObject(text: string, label: string) {
  const clean = text.trim();
  if (!clean) {
    return {};
  }
  const parsed = JSON.parse(clean);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象。`);
  }
  return parsed;
}

function formatJson(value: any) {
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return "{}";
  }
}

async function loadSkillStats() {
  settingsNotice.value = "";
  const data = await runPanelCommand("/skills-stats", { refresh: false });
  skillStatsText.value = data.text || "暂无使用统计。";
}

async function loadMcpStatus() {
  mcpNotice.value = "";
  const data = await runPanelCommand("/mcp", { refresh: false });
  mcpStatusText.value = data.text || "暂无 MCP 状态。";
}

function openAuditPanel() {
  activeSection.value = "audit";
  loadFullAudit();
}

async function loadFullAudit() {
  auditNotice.value = "";
  const data = await runPanelCommand("/audit", { refresh: false });
  auditNotice.value = data.text || "";
  auditPanelRecords.value = Array.isArray(data.records) ? data.records : [];
}

async function loadTaskStatus() {
  const data = await runPanelCommand("/task", { refresh: false });
  taskCommandText.value = data.text || "";
}

async function resumeTask() {
  const id = recoveryTask.value?.id || "";
  if (!id) {
    taskCommandText.value = "当前没有可恢复的任务。";
    return;
  }
  const data = await runPanelCommand({ command: "task_resume", id, text: `/task-resume ${id}` });
  taskCommandText.value = data.text || "";
}

async function searchMemory() {
  if (!memoryQuery.value.trim()) {
    return;
  }
  const data = await runPanelCommand({
    command: "memory_search",
    query: memoryQuery.value.trim(),
    text: `/memory-search ${memoryQuery.value.trim()}`
  }, { refresh: false });
  memoryCommandText.value = data.text || "";
  memorySearchResults.value = Array.isArray(data.results) ? data.results : [];
}

async function forgetMemory() {
  if (!forgetId.value.trim()) {
    return;
  }
  const data = await runPanelCommand({
    command: "memory_forget",
    id: forgetId.value.trim(),
    text: `/memory-forget ${forgetId.value.trim()}`
  });
  memoryCommandText.value = data.text || "";
  if (data.ok) {
    forgetId.value = "";
  }
}

async function clearMemory() {
  const data = await runPanelCommand("/memory-clear");
  memoryCommandText.value = data.text || "";
  if (data.ok) {
    memorySearchResults.value = [];
  }
}

async function abandonTask() {
  const id = currentTask.value?.id || "";
  const data = await runPanelCommand({ command: "task_cancel", id, text: "/task-cancel" });
  taskCommandText.value = data.text || "";
}

async function addCron() {
  if (!cronPrompt.value.trim() || !cronMinutes.value) {
    return;
  }
  const data = await runPanelCommand({
    command: "cron_add",
    interval_minutes: Number(cronMinutes.value),
    prompt: cronPrompt.value.trim(),
    text: `/cron-add ${cronMinutes.value} ${cronPrompt.value.trim()}`
  });
  cronNotice.value = data.text || "";
  if (data.ok) {
    cronPrompt.value = "";
  }
}

async function removeCron(task: any) {
  const id = task.id || task.name || "";
  if (!id) {
    return;
  }
  const data = await runPanelCommand({ command: "cron_remove", id, text: `/cron-remove ${id}` });
  cronNotice.value = data.text || "";
}

async function loadToolDiagnostics() {
  diagnosticsLoading.value = "tools";
  toolNotice.value = "";
  try {
    const response = await fetch("/api/tools/diagnostics");
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.text || data.error || `Tools diagnostics API ${response.status}`);
    }
    toolDiagnosticsOverride.value = data.diagnostics || null;
    toolNotice.value = "工具诊断已更新。";
  } catch (err) {
    toolNotice.value = `工具诊断失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    diagnosticsLoading.value = "";
  }
}

function toolRiskLabel(risk: any) {
  const value = String(risk || "unknown");
  if (value === "low") {
    return "低风险";
  }
  if (value === "medium") {
    return "中风险";
  }
  if (value === "high") {
    return "高风险";
  }
  if (value === "dynamic") {
    return "动态判断";
  }
  return "未知风险";
}

function toolRiskIcon(risk: any) {
  const value = String(risk || "unknown");
  if (value === "low") {
    return "🍃";
  }
  if (value === "medium") {
    return "💎";
  }
  if (value === "high") {
    return "🔥";
  }
  if (value === "dynamic") {
    return "🧭";
  }
  return "✨";
}

function toolPermissionLabel(permission: any) {
  const value = String(permission || "unknown");
  if (value === "allow") {
    return "自动运行";
  }
  if (value === "ask") {
    return "需要确认";
  }
  if (value === "deny") {
    return "已禁用";
  }
  if (value === "dynamic") {
    return "按目标判断";
  }
  return "未配置";
}

function toolExposureLabel(exposure: any) {
  const value = String(exposure || "direct");
  if (value === "deferred") {
    return "延迟检索";
  }
  if (value === "bridge") {
    return "检索桥接";
  }
  return "直接可见";
}

function memoryResultKey(item: any) {
  return String(item?.id ?? item?.memory_id ?? item?.source ?? item?.text ?? JSON.stringify(item));
}

function memoryResultTitle(item: any) {
  const id = item?.id ?? item?.memory_id;
  const kind = item?.kind || item?.type || item?.source || "memory";
  return id ? `#${id} · ${kind}` : String(kind);
}

function memoryResultDescription(item: any) {
  return String(item?.text || item?.content || item?.summary || item?.memory || JSON.stringify(item));
}

function memoryResultMeta(item: any) {
  const score = item?.score ?? item?.distance ?? item?.similarity;
  if (typeof score === "number") {
    return score.toFixed(3);
  }
  return item?.provider || "";
}

function providerDescription(provider: any) {
  if (provider.name === "markdown") {
    return `MEMORY ${provider.memory_entries || 0} 条 · USER ${provider.user_entries || 0} 条`;
  }
  if (provider.name === "local_vector") {
    return `${provider.records || 0} 条 · ${provider.embedding_model || "embedding"}`;
  }
  return "ready";
}

const SectionTitle = defineComponent({
  props: {
    title: { type: String, required: true },
    description: { type: String, default: "" }
  },
  setup(props) {
    return () => h("div", { class: "section-title-block" }, [
      h("h3", props.title),
      props.description ? h("p", props.description) : null
    ]);
  }
});

const ListRow = defineComponent({
  props: {
    title: { type: String, required: true },
    description: { type: String, default: "" },
    meta: { type: String, default: "" }
  },
  setup(props) {
    return () => h("div", { class: "settings-row" }, [
      h("span", [
        h("strong", props.title),
        props.description ? h("small", props.description) : null
      ]),
      props.meta ? h("b", props.meta) : null
    ]);
  }
});

const PanelResult = defineComponent({
  props: {
    title: { type: String, required: true },
    text: { type: String, default: "" }
  },
  setup(props) {
    return () => h("div", { class: "settings-panel-result" }, [
      h("strong", props.title),
      h("pre", props.text || "暂无结果。")
    ]);
  }
});
</script>
