const $ = mdui.$
let CTX
const configKey = "fileBrowserConfig";
const SEARCH_ENDPOINT = '/api/search';
const SEARCH_DEBOUNCE_MS = 150;
const SEARCH_RENDER_FRAME_BUDGET_MS = 8;
const DESKTOP_SEARCH_LEFT_INSET = 72;
const DESKTOP_SEARCH_TITLE_GAP = 24;
let searchRenderId = 0
const defaultConfig = {
    theme: 'auto',
    primary: 'teal',
    accent: 'teal',
}

/**
 * 入口
 */
$(function main() {
    FileBrowserI18n.init()
    CTX = new FileBrowserContext()

    initTheme(loadConfig())
    initTitle()
    initPathList()
    initFileDetail()
    initSortMenu()
    FileBrowserI18n.onChange(initSortMenu)

    registerCopyEvent()
    registerSearchFileEvent()
})

/**
 * 初始化标题
 */
function initTitle() {
    const title = document.title.trim()
    $('.m-appbar-title').text(title)
}

/**
 * 初始化左边的index列表
 */
function initPathList() {
    let $pathList = $('.m-list-index');
    CTX.chain.forEach((fileContext, i) => {
        const active = i === CTX.chain.length - 1
        const item = genPathListItem(fileContext, active)
        $pathList.append(item)
    })
}

/**
 * 生成路径列表项
 */
function genPathListItem(fileContext, active) {
    const stateClass = active ? 'mdui-list-item-active' : ''
    return $(`<div class="mdui-list-item mdui-ripple ${stateClass}">
                <a href="${fileContext.href + window.location.search}">
                    <i class="mdui-list-item-icon mdui-icon material-icons mdui-text-color-theme">${fileContext.icon}</i>
                    <span class="mdui-list-item-content mdui-text-color-theme">${fileContext.name}</span>
                </a>
            </div>`)
}

/**
 * 生成文件详情
 */
function initFileDetail() {
    const folders = []
    const files = []
    CTX.files.forEach(fileContext => {
        if (fileContext.isDir) {
            folders.push(genFileDetailItem(fileContext))
        } else {
            files.push(genFileDetailItem(fileContext))
        }
    })

    let $mFileDetail = $(`.m-file-detail`);
    if (folders.length > 0) {
        $mFileDetail.append(genFileDetailItemDivideLine('folders'))
        folders.forEach(item => $mFileDetail.append(item))
    }
    if (files.length > 0) {
        $mFileDetail.append(genFileDetailItemDivideLine('files'))
        files.forEach(item => $mFileDetail.append(item))
    }

    $mFileDetail.after('<div class="mdui-list m-search-results mdui-hidden"></div>')
}

/**
 * 生成文件详情项
 */
function genFileDetailItem(fileContext, subtitle) {
    const $item = $('<div class="mdui-list-item mdui-ripple">').attr('data-file-name', fileContext.name)
    const $icon = $('<a class="mdui-list-item-avatar mdui-icon material-icons mdui-color-theme">')
        .attr('href', fileContext.href)
        .text(fileContext.icon)
    const $content = $('<a class="mdui-list-item-content">').attr('href', fileContext.href)
    const $title = $('<div class="mdui-list-item-title">').text(fileContext.name)
    if (fileContext.goBack) $title.attr('data-i18n', 'parent')
    const $subtitle = $('<div class="mdui-list-item-text">').text(subtitle === undefined ? (fileContext.date || '') : subtitle)
    const $size = $('<span class="m-file-size mdui-text-color-theme">').text(fileContext.size || '')
    const $copyButton = $('<button class="mdui-btn mdui-btn-icon mdui-btn-dense mdui-text-color-theme-text mdui-ripple m-file-copy" type="button" data-i18n-tooltip="copy" mdui-tooltip="{content: \'复制链接\'}">')
        .attr('data-copy-link', fileContext.href)
        .append('<i class="mdui-icon material-icons">content_copy</i>')

    $content.append($title).append($subtitle)
    const $result = $item.append($icon).append($content).append($size).append($copyButton)
    FileBrowserI18n.applyTranslations($result[0])
    return $result
}

function registerCopyEvent() {
    document.addEventListener('click', event => {
        const copyButton = event.target.closest('.m-file-copy')
        if (!copyButton) return

        event.preventDefault()
        copyText(copyButton.dataset.copyLink || '')
    })
}

/**
 * 生成文件详情项分割线
 */
function genFileDetailItemDivideLine(key, values) {
    const $divider = $('<div class="mdui-subheader-inset">')
        .attr('data-i18n', key)
        .text(FileBrowserI18n.translate(key, values))
    if (values && values.count !== undefined) $divider.attr('data-i18n-count', values.count)
    return $divider
}

/**
 * 初始化排序菜单：新字段始终从升序开始，当前字段再次选择时切换方向。
 */
function initSortMenu() {
    const currentUrl = new URL(window.location.href)
    const currentColumn = (currentUrl.searchParams.get('C') || '').toUpperCase()
    const currentOrder = (currentUrl.searchParams.get('O') || 'A').toUpperCase()

    $('.m-sort-option').each((_, element) => {
        const column = element.dataset.sortColumn
        const isCurrentColumn = column === currentColumn
        const nextOrder = isCurrentColumn && currentOrder === 'A' ? 'D' : 'A'
        const targetUrl = new URL(currentUrl)
        targetUrl.searchParams.set('C', column)
        targetUrl.searchParams.set('O', nextOrder)

        element.href = `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`
        const label = element.querySelector('span').textContent.trim()
        const direction = FileBrowserI18n.translate(nextOrder === 'A' ? 'sort.ascending' : 'sort.descending')
        element.setAttribute('aria-label', `${label} (${direction})`)

        const directionIcon = element.querySelector('.m-sort-direction')
        directionIcon.textContent = isCurrentColumn
            ? (currentOrder === 'D' ? 'arrow_downward' : 'arrow_upward')
            : 'unfold_more'
    })

    const resetUrl = new URL(currentUrl)
    resetUrl.searchParams.delete('C')
    resetUrl.searchParams.delete('O')
    const resetLink = document.querySelector('.m-sort-reset')
    resetLink.href = `${resetUrl.pathname}${resetUrl.search}${resetUrl.hash}`
    resetLink.setAttribute('aria-label', resetLink.textContent.trim())
}

/**
 * 文件搜索事件
 */
function registerSearchFileEvent() {
    const $search = $('.m-file-search')
    const $searchShell = $('.m-file-search-shell')
    const $searchTrigger = $('.m-file-search-trigger')
    const $searchClear = $('.m-file-search-clear')
    const $appbarTitle = $('.m-appbar-title')
    let timer
    let requestId = 0
    let activeSearchRequest

    function isMobileSearch() {
        return window.matchMedia('(max-width: 599px)').matches
    }

    function alignDesktopSearch() {
        if (isMobileSearch() || !$searchShell.hasClass('m-file-search-open')) return

        const visibleResults = document.querySelector('.m-search-results:not(.mdui-hidden)')
        const searchScope = visibleResults || document.querySelector('.m-file-detail')
        const bounds = searchScope.getBoundingClientRect()
        const triggerBounds = $searchTrigger[0].getBoundingClientRect()
        const searchLeft = Math.round(bounds.left + DESKTOP_SEARCH_LEFT_INSET)
        const titleLeft = $appbarTitle[0].getBoundingClientRect().left

        $searchShell[0].style.setProperty('--m-search-left', `${searchLeft}px`)
        $searchShell[0].style.setProperty('--m-search-right', `${Math.round(window.innerWidth - triggerBounds.left)}px`)
        $appbarTitle[0].style.maxWidth = `${Math.max(0, searchLeft - titleLeft - DESKTOP_SEARCH_TITLE_GAP)}px`
    }

    function setDesktopSearchTriggerState(isOpen) {
        const icon = $searchTrigger.find('.mdui-icon')[0]
        const tooltipKey = isOpen ? 'close' : 'search'

        icon.textContent = tooltipKey
        $searchTrigger.attr('data-i18n-tooltip', tooltipKey)
        FileBrowserI18n.applyTranslations($searchTrigger[0])
    }

    function openSearch() {
        $searchShell.addClass('m-file-search-open')
        alignDesktopSearch()
        if (isMobileSearch()) {
            $searchTrigger.addClass('m-file-search-trigger-inactive')
        } else {
            setDesktopSearchTriggerState(true)
        }
        $search[0].focus()
    }

    function closeSearch() {
        $searchShell.removeClass('m-file-search-open')
        $searchTrigger.removeClass('m-file-search-trigger-inactive')
        $appbarTitle[0].style.removeProperty('max-width')
        setDesktopSearchTriggerState(false)
        $search[0].blur()
    }

    function syncSearchMode() {
        if (!$searchShell.hasClass('m-file-search-open')) return

        if (isMobileSearch()) {
            $searchTrigger.addClass('m-file-search-trigger-inactive')
            $appbarTitle[0].style.removeProperty('max-width')
            return
        }

        $searchTrigger.removeClass('m-file-search-trigger-inactive')
        setDesktopSearchTriggerState(true)
        alignDesktopSearch()
    }

    $searchTrigger.on('click', event => {
        event.preventDefault()
        event.stopPropagation()
        if (!isMobileSearch() && $searchShell.hasClass('m-file-search-open')) {
            closeSearch()
            return
        }
        openSearch()
    })

    $searchClear.on('click', event => {
        event.preventDefault()
        event.stopPropagation()
        closeSearch()
    })

    document.addEventListener('pointerdown', event => {
        if (isMobileSearch()
            && !$searchShell[0].contains(event.target)
            && !$searchTrigger[0].contains(event.target)) {
            closeSearch()
        }
    })
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && $searchShell.hasClass('m-file-search-open')) closeSearch()
    })
    window.addEventListener('resize', syncSearchMode)

    $search.on('input', () => {
        const keyword = ($search.val() || '').trim()
        window.clearTimeout(timer)
        requestId += 1
        cancelSearchRendering()
        if (activeSearchRequest) activeSearchRequest.abort()

        if (!keyword) {
            showCurrentDirectory()
            return
        }

        const currentRequestId = requestId
        timer = window.setTimeout(async () => {
            const controller = new AbortController()
            activeSearchRequest = controller
            showSearchLoading()
            try {
                const results = await searchRecursively(keyword, controller.signal)
                if (currentRequestId === requestId) {
                    showSearchResults(results)
                }
            } catch (error) {
                if (error.name === 'AbortError') return
                if (currentRequestId === requestId) {
                    filterCurrentDirectory(keyword)
                }
            } finally {
                if (activeSearchRequest === controller) activeSearchRequest = undefined
            }
        }, SEARCH_DEBOUNCE_MS)
    })
}

async function searchRecursively(keyword, signal) {
    const parameters = new URLSearchParams({
        path: decodeCurrentPath(),
        q: keyword,
    })
    const response = await fetch(`${SEARCH_ENDPOINT}?${parameters.toString()}`, {signal})
    if (!response.ok) {
        throw new Error(`search request failed: ${response.status}`)
    }
    const payload = await response.json()
    if (!Array.isArray(payload.results)) {
        throw new Error('search response is malformed')
    }
    return payload.results
}

function decodeCurrentPath() {
    try {
        return decodeURIComponent(window.location.pathname)
    } catch (error) {
        return window.location.pathname
    }
}

function cancelSearchRendering() {
    searchRenderId += 1
}

function showSearchLoading() {
    const $results = $('.m-search-results').empty().removeClass('mdui-hidden')
    $('.m-file-detail').addClass('mdui-hidden')
    $results.append(genFileDetailItemDivideLine('search.results', {count: 0}))
}

function showSearchResults(results) {
    const renderId = ++searchRenderId
    const $results = $('.m-search-results').empty().removeClass('mdui-hidden')
    $('.m-file-detail').addClass('mdui-hidden')
    const $divider = genFileDetailItemDivideLine('search.results', {count: 0})
    $results.append($divider)

    renderSearchResultBatch($results[0], $divider[0], results, 0, renderId)
}

function updateSearchResultCount(divider, count) {
    divider.dataset.i18nCount = String(count)
    divider.textContent = FileBrowserI18n.translate('search.results', {count})
}

function renderSearchResultBatch(container, divider, results, start, renderId) {
    if (renderId !== searchRenderId) return

    const fragment = document.createDocumentFragment()
    const deadline = performance.now() + SEARCH_RENDER_FRAME_BUDGET_MS
    let end = start
    while (end < results.length) {
        const result = results[end]
        const fileContext = {
            name: result.name,
            href: encodePath(result.relative_path),
            icon: result.is_dir ? 'folder' : 'description',
            size: result.is_dir ? '' : formatFileSize(result.size),
        }
        fragment.appendChild(genFileDetailItem(fileContext, result.relative_path)[0])
        end += 1
        if (performance.now() >= deadline) break
    }
    container.appendChild(fragment)
    updateSearchResultCount(divider, end)

    if (end < results.length) {
        window.requestAnimationFrame(() => {
            renderSearchResultBatch(container, divider, results, end, renderId)
        })
        return
    }
}

function showCurrentDirectory() {
    cancelSearchRendering()
    $('.m-search-results').empty().addClass('mdui-hidden')
    $('.m-file-detail').removeClass('mdui-hidden')
    $('.m-file-detail > .mdui-list-item').removeClass('mdui-hidden')
}

function filterCurrentDirectory(keyword) {
    cancelSearchRendering()
    $('.m-search-results').empty().addClass('mdui-hidden')
    $('.m-file-detail').removeClass('mdui-hidden')
    $('.m-file-detail > .mdui-list-item').each((_, element) => {
        const fileName = element.dataset.fileName || ''
        element.classList.toggle('mdui-hidden', !fileName.includes(keyword))
    })
}

function encodePath(path) {
    return path.split('/').map(segment => encodeURIComponent(segment)).join('/')
}

function formatFileSize(size) {
    if (!Number.isFinite(size) || size < 1) {
        return ''
    }
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    const unitIndex = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1)
    const value = size / Math.pow(1024, unitIndex)
    return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
}

/**
 * 复制字符
 */
function copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
        mdui.snackbar({
            message: FileBrowserI18n.translate('copy.success'),
            position: 'top',
            onOpen(instance) {
                instance.$element.addClass('m-copy-snackbar')
            },
        })
    });
}

/**
 * 初始主题
 */
function initTheme(themeConfig) {
    themeConfig = themeConfig || defaultConfig
    let $body = $('body');
    $body.removeClass()
    $body.addClass(`mdui-theme-primary-${themeConfig.primary} mdui-theme-accent-${themeConfig.accent}  mdui-theme-layout-${themeConfig.theme}`)

    $(`.m-theme-theme input[value=${themeConfig.theme}]`).prop('checked', true)
    $(`.m-theme-primary input[value=${themeConfig.primary}]`).prop('checked', true)
    $(`.m-theme-accent input[value=${themeConfig.accent}]`).prop('checked', true)
}

/**
 * 重置主题
 */
function resetTheme() {
    clearConfig()
    initTheme(defaultConfig)
}

/**
 * 手动设置主题
 */
function changeTheme() {
    const themeConfig = {
        theme: $('.m-theme-theme input:checked').val(),
        primary: $('.m-theme-primary input:checked').val(),
        accent: $('.m-theme-accent input:checked').val()
    }
    setConfig(themeConfig)
    initTheme(themeConfig)
}

/**
 * 载入配置
 */
function loadConfig() {
    try {
        const config = localStorage.getItem(configKey)
        if (config == null) return defaultConfig

        const themeConfig = JSON.parse(config)
        if (isThemeConfig(themeConfig)) return themeConfig
    } catch (error) {
        // 浏览器可能保留了旧版本写入的无效配置，例如字符串 "undefined"。
    }

    clearConfig()
    return defaultConfig
}

/**
 * 设置配置
 */
function setConfig(themeConfig) {
    if (!isThemeConfig(themeConfig)) {
        clearConfig()
        return
    }

    try {
        localStorage.setItem(configKey, JSON.stringify(themeConfig))
    } catch (error) {
        // 本地存储被禁用时，主题仍可在当前页面生效。
    }
}

function clearConfig() {
    try {
        localStorage.removeItem(configKey)
    } catch (error) {
        // 本地存储被禁用时无需额外处理。
    }
}

function isThemeConfig(themeConfig) {
    if (!themeConfig || typeof themeConfig !== 'object') return false

    return ['auto', 'light', 'dark'].includes(themeConfig.theme)
        && typeof themeConfig.primary === 'string'
        && typeof themeConfig.accent === 'string'
}
