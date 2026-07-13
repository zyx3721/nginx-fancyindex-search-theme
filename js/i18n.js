const FileBrowserI18n = (() => {
    const storageKey = 'fileBrowserLanguage'
    const listeners = []
    const messages = {
        zh: {
            search: '搜索',
            close: '关闭',
            sort: '排序',
            'sort.date': '按日期',
            'sort.name': '按名称',
            'sort.size': '按大小',
            'sort.ascending': '升序',
            'sort.descending': '降序',
            'sort.reset': '恢复默认排序',
            'theme.settings': '主题设置',
            'language.switch': '切换为英文',
            folders: '文件夹',
            files: '文件',
            parent: '上级目录',
            'search.results': '搜索结果（{count}）',
            copy: '复制链接',
            'copy.success': '链接已复制到剪贴板',
            'theme.appearance': '界面模式',
            'theme.auto': '跟随系统',
            'theme.light': '浅色',
            'theme.dark': '深色',
            'theme.primary': '主色',
            'theme.accent': '强调色',
            'theme.reset': '恢复默认主题',
            confirm: '确定',
            'color.amber': '琥珀色',
            'color.blue': '蓝色',
            'color.blue-grey': '蓝灰色',
            'color.brown': '棕色',
            'color.cyan': '青色',
            'color.deep-orange': '深橙色',
            'color.deep-purple': '深紫色',
            'color.green': '绿色',
            'color.grey': '灰色',
            'color.indigo': '靛蓝色',
            'color.light-blue': '浅蓝色',
            'color.light-green': '浅绿色',
            'color.lime': '青柠色',
            'color.orange': '橙色',
            'color.pink': '粉色',
            'color.purple': '紫色',
            'color.red': '红色',
            'color.teal': '蓝绿色',
            'color.yellow': '黄色',
        },
        en: {
            search: 'Search',
            close: 'Close',
            sort: 'Sort',
            'sort.date': 'By Date',
            'sort.name': 'By Name',
            'sort.size': 'By Size',
            'sort.ascending': 'Ascending',
            'sort.descending': 'Descending',
            'sort.reset': 'Restore Default Sort',
            'theme.settings': 'Theme Settings',
            'language.switch': 'Switch to Chinese',
            folders: 'Folders',
            files: 'Files',
            parent: 'Parent Directory',
            'search.results': 'Search Results ({count})',
            copy: 'Copy Link',
            'copy.success': 'Link copied to clipboard',
            'theme.appearance': 'Appearance',
            'theme.auto': 'Auto',
            'theme.light': 'Light',
            'theme.dark': 'Dark',
            'theme.primary': 'Primary Color',
            'theme.accent': 'Accent Color',
            'theme.reset': 'Restore Default Theme',
            confirm: 'OK',
            'color.amber': 'Amber',
            'color.blue': 'Blue',
            'color.blue-grey': 'Blue Grey',
            'color.brown': 'Brown',
            'color.cyan': 'Cyan',
            'color.deep-orange': 'Deep Orange',
            'color.deep-purple': 'Deep Purple',
            'color.green': 'Green',
            'color.grey': 'Grey',
            'color.indigo': 'Indigo',
            'color.light-blue': 'Light Blue',
            'color.light-green': 'Light Green',
            'color.lime': 'Lime',
            'color.orange': 'Orange',
            'color.pink': 'Pink',
            'color.purple': 'Purple',
            'color.red': 'Red',
            'color.teal': 'Teal',
            'color.yellow': 'Yellow',
        },
    }
    let language = 'zh'

    function normalizeLanguage(value) {
        return value === 'en' ? 'en' : 'zh'
    }

    function translate(key, values = {}) {
        const template = messages[language][key] || messages.zh[key] || key
        return template.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? '')
    }

    function findTextNode(element) {
        return Array.from(element.childNodes)
            .reverse()
            .find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
    }

    function updateTooltip(element, content) {
        const escapedContent = content.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
        const position = element.dataset.tooltipPosition
        const positionOption = position ? `, position: '${position}'` : ''
        element.setAttribute('mdui-tooltip', `{content: '${escapedContent}'${positionOption}}`)
        element.setAttribute('aria-label', content)

        if (!window.mdui) return
        const instance = mdui.$(element).data('_mdui_tooltip')
        if (instance) {
            instance.options.content = content
            instance.$element.text(content)
        }
    }

    function forEachElement(root, selector, callback) {
        if (root.matches && root.matches(selector)) callback(root)
        root.querySelectorAll(selector).forEach(callback)
    }

    function applyTranslations(root = document) {
        forEachElement(root, '[data-i18n]', element => {
            element.textContent = translate(element.dataset.i18n, {count: element.dataset.i18nCount})
        })
        forEachElement(root, '[data-i18n-placeholder]', element => {
            element.placeholder = translate(element.dataset.i18nPlaceholder)
        })
        forEachElement(root, '[data-i18n-tooltip]', element => {
            updateTooltip(element, translate(element.dataset.i18nTooltip))
        })
        forEachElement(root, 'input[name="doc-theme-primary"], input[name="doc-theme-accent"]', input => {
            const textNode = findTextNode(input.parentElement)
            if (textNode) textNode.textContent = ` ${translate(`color.${input.value}`)}`
        })
        document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
    }

    function setLanguage(value, persist = true) {
        language = normalizeLanguage(value)
        if (persist) {
            try {
                localStorage.setItem(storageKey, language)
            } catch (error) {
                console.warn('Unable to save language preference.', error)
            }
        }
        applyTranslations()
        listeners.forEach(listener => listener(language))
    }

    function positionLanguageTooltip() {
        const button = document.querySelector('.m-language-toggle')
        const tooltip = mdui.$(button).data('_mdui_tooltip')
        if (!tooltip) return

        const targetRect = button.getBoundingClientRect()
        const targetOffset = mdui.$(button).offset()
        const tooltipWidth = tooltip.$element[0].offsetWidth
        const targetMargin = window.innerWidth > 1024 ? 14 : 24
        const left = Math.max(8, targetOffset.left + targetRect.width - tooltipWidth)
        const top = targetOffset.top + targetRect.height + targetMargin

        tooltip.$element
            .addClass('m-language-tooltip')
            .css({
                top: `${top}px`,
                left: `${left}px`,
                'margin-left': '0',
                'margin-top': '0',
            })
            .transformOrigin('top right')
    }

    function init() {
        try {
            language = normalizeLanguage(localStorage.getItem(storageKey))
        } catch (error) {
            language = 'zh'
        }
        applyTranslations()
        const languageButton = document.querySelector('.m-language-toggle')
        languageButton.addEventListener('click', () => {
            setLanguage(language === 'zh' ? 'en' : 'zh')
        })
        languageButton.addEventListener('mouseover', () => window.setTimeout(positionLanguageTooltip))
    }

    return {
        applyTranslations,
        init,
        onChange(listener) {
            listeners.push(listener)
        },
        setLanguage,
        translate,
    }
})()
