let map;
let allRuns = [];
let filteredRuns = [];
let currentPage = 1;
const itemsPerPage = 16;

const firstRunDate = new Date("3/24/2021");

let currentYearFilter = 'all';
let currentMonthFilter = null; 
let currentTypeFilter = 'all';
let mediaRunIds = [];
let isMediaRunIdsLoaded = false;

let currentActiveRunId = null;
let currentActiveRunWeatherStr = null;
let currentSingleRun = null; 

let currentMediaMarkers = []; // 存放地图上的多媒体标记
let currentMediaData = null;  // 存放当前运动的多媒体数据
let targetHeatmapYear = new Date().getFullYear();
// Chart Instances
let paceChartInstance = null;
let hrChartInstance = null;
let monthlyMileageChartInstance = null; // 新增按月跑量图表实例

// Tanda Prediction state
let isPredictionLoaded = false;
let tandaTrendChartInstance = null;
let tandaProgChartInstance = null;

// Races / PB state
let pbLoaded = false;
let racesRendered = false;
let allRaceActivities = [];
let detailMapInstance = null;

const GOAL_TOTAL = 40000;
const GOAL_YEARLY = 2400;
const GOAL_MONTHLY = 200;
const HALF_MARATHON = 21.0975;
const MY_MAPTILER_KEY = 'qe8S22pu1TsIRYiuyJ1f';

async function loadMediaRunIds() {
    if (isMediaRunIdsLoaded) return;
    try {
        const res = await fetch('https://workerrunapi.linwn.net/api/media/list');
        if (res.ok) {
            mediaRunIds = await res.json();
            isMediaRunIdsLoaded = true;
        }
    } catch (err) {
        console.error("获取多媒体记录列表失败:", err);
    }
}

function getTodayDateString() {
    const now = new Date();
    return `${now.getFullYear()}-${(now.getMonth()+1).toString().padStart(2,'0')}-${now.getDate().toString().padStart(2,'0')}`;
}

// --- Settings & Theme Application ---
function applyThemeAndColor(theme, color) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.setProperty('--accent-color', color);
    
    const bgOpacity = theme === 'light' ? 0.08 : 0.12;
    document.documentElement.style.setProperty('--active-row-bg', hexToRgbaFast(color, bgOpacity));

    const styleUrl = theme === 'light' ? 'https://tiles.openfreemap.org/styles/positron' : 'https://run.linwn.net/dark_matter.json';

    if (map && map.loaded()) {
        map.setStyle(styleUrl);
        map.once('styledata', () => {
             if (map.getLayer('route-layer')) {
                 map.setPaintProperty('route-layer', 'line-color', color);
             }
        });
    }

    if (detailMapInstance && detailMapInstance.loaded()) {
        detailMapInstance.setStyle(styleUrl);
        detailMapInstance.once('styledata', () => {
             if (detailMapInstance.getLayer('detail-route-layer')) {
                 detailMapInstance.setPaintProperty('detail-route-layer', 'line-color', color);
             }
        });
    }

    if (typeof renderRecent4Weeks === 'function') {
        renderRecent4Weeks();
    }
    
    if (monthlyMileageChartInstance) {
        monthlyMileageChartInstance.dispose();
        monthlyMileageChartInstance = null;
        renderMonthlyMileageChart();
    }
    
    if (isPredictionLoaded) {
        updatePredictionPage();
    }
}

function initMap() {
    const theme = localStorage.getItem('theme') || 'dark';
    const styleUrl = theme === 'light' ? 'https://tiles.openfreemap.org/styles/positron' : 'https://run.linwn.net/dark_matter.json';
    
    map = new maplibregl.Map({
        container: 'map',
        style: styleUrl,
        center: [113.3, 23.1], 
        zoom: 11,
        preserveDrawingBuffer: true, 
        attributionControl: false,
		transformRequest: (url, resourceType) => {
			if (url.includes('{key}')) {
				return {
					url: url.replace('{key}', MY_MAPTILER_KEY)
				};
			}
			return { url: url };
		}
    });

    map.addControl(new maplibregl.FullscreenControl(), 'top-right');
}

function renderMap(runsOrRun) {
    if (!map.loaded()) {
        map.once('load', () => { renderMap(runsOrRun); });
        return;
    }

    let runs = Array.isArray(runsOrRun) ? runsOrRun : (runsOrRun ? [runsOrRun] : []);
    let features = [];
    
    if (runs.length === 1) {
        currentSingleRun = runs[0];
        document.getElementById('toggle-map-chart-btn').style.display = 'flex';
    } else {
        currentSingleRun = null;
        document.getElementById('toggle-map-chart-btn').style.display = 'none';
        document.getElementById('run-charts-container').style.display = 'none';
        document.getElementById('map').style.display = 'block';
		clearMediaMarkers();
    }

    runs.forEach(run => {
        if (run && run._cachedLatlngs && run._cachedLatlngs.length > 0) {
            let geojsonCoords = run._cachedLatlngs.map(coord => [coord[1], coord[0]]);
            features.push({
                'type': 'Feature',
                'geometry': { 'type': 'LineString', 'coordinates': geojsonCoords }
            });
        }
    });

    const geojsonData = { 'type': 'FeatureCollection', 'features': features };
    const sourceId = 'route-source';
    const layerId = 'route-layer';
    const accentColor = localStorage.getItem('accentColor') || '#e93342';

    if (map.getSource(sourceId)) {
        map.getSource(sourceId).setData(geojsonData);
    } else {
        map.addSource(sourceId, { 'type': 'geojson', 'data': geojsonData });
        map.addLayer({
            'id': layerId,
            'type': 'line',
            'source': sourceId,
            'layout': { 'line-join': 'round', 'line-cap': 'round' },
            'paint': { 'line-color': accentColor, 'line-width': 2, 'line-opacity': 0.4 }
        });
    }

    if (map.getLayer(layerId)) {
        map.setPaintProperty(layerId, 'line-color', accentColor);
        map.setPaintProperty(layerId, 'line-width', 2);
        map.setPaintProperty(layerId, 'line-opacity', runs.length === 1 ? 0.9 : 0.4);
    }

    if (features.length > 0) {
        let pointsToFit = [];

        if (runs.length === 1) {
            pointsToFit = features[0].geometry.coordinates;
        } else {
            const centerMode = localStorage.getItem('mapCenterMode') || 'A';
            
            if (centerMode === 'A') {
                const latestFeature = features.find(f => f.geometry.coordinates.length > 0);
                if (latestFeature) {
                    const coords = latestFeature.geometry.coordinates;
                    const pLng = coords.map(p => p[0]);
                    const pLat = coords.map(p => p[1]);
                    const cLng = (Math.min(...pLng) + Math.max(...pLng)) / 2;
                    const cLat = (Math.min(...pLat) + Math.max(...pLat)) / 2;
                    map.easeTo({ center: [cLng, cLat], zoom: 11 });
                    return; 
                }
            } else if (centerMode === 'B') {
                const lng = parseFloat(localStorage.getItem('mapCenterLng')) || 113.3;
                const lat = parseFloat(localStorage.getItem('mapCenterLat')) || 23.1;
                map.easeTo({ center: [lng, lat], zoom: 11 });
                return; 
            } else if (centerMode === 'C') {
                for (const f of features) {
                    pointsToFit = pointsToFit.concat(f.geometry.coordinates);
                }
            }
        }

        if (pointsToFit.length === 0) {
            map.easeTo({ center: [20, 20], zoom: 3 });
        } else if (pointsToFit.length === 2 && String(pointsToFit[0]) === String(pointsToFit[1])) {
            map.easeTo({ center: pointsToFit[0], zoom: 9 });
        } else {
            const pointsLong = pointsToFit.map(point => point[0]);
            const pointsLat = pointsToFit.map(point => point[1]);
            const bounds = [
                [Math.min(...pointsLong), Math.min(...pointsLat)],
                [Math.max(...pointsLong), Math.max(...pointsLat)]
            ];
            map.fitBounds(bounds, { padding: 40 });
        }
    }
}

function parseMovingTime(timeStr) {
    if (!timeStr) return 0;
    const parts = timeStr.split('.')[0].split(':');
    let seconds = 0;
    if (parts.length === 3) {
        seconds += parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseInt(parts[2], 10);
    } else if (parts.length === 2) {
        seconds += parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    }
    return seconds;
}

function formatHoursMins(totalSeconds) {
    const hours = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    return `${hours}h ${mins}m`;
}

function updateMapInfoBox(type, data, weather = null) {
    const box = document.getElementById('map-info-text');
    const flipBtn = document.getElementById('toggle-map-chart-btn');
    if (!box) return;

    if (type === 'summary') {
        flipBtn.style.display = 'none';
        let yearText = currentYearFilter === 'all' ? '总计' : `${currentYearFilter}年`;
        if (currentMonthFilter) {
            yearText = `${currentYearFilter === 'all' ? '' : currentYearFilter + '年'}${currentMonthFilter}月`;
        }
        const dist = data.dist.toFixed(2);
        box.innerHTML = `<span style="flex:1; overflow:hidden; text-overflow:ellipsis;"><strong class="info-strong">${yearText}概览</strong> &middot; ${data.runs} 次活动 / ${dist} km / 耗时 ${formatHoursMins(data.seconds)}</span>`;
    } else if (type === 'single') {
        flipBtn.style.display = 'flex';
        const dateFull = data.start_date_local || '';
        const dateShort = dateFull.substring(0, 10);
        const dist = ((data.distance || 0) / 1000).toFixed(2);
        
        let weatherHtml = '';
        if (weather) {
            const condition = weather.condition || "";
            const emojiMatch = condition.match(/\p{Extended_Pictographic}/gu);
            const emoji = emojiMatch ? emojiMatch[emojiMatch.length - 1] : '';
            currentActiveRunWeatherStr = `${emoji} ${weather.temperature_c}°C`.trim();
            weatherHtml = `<span class="weather-text" style="margin-left: auto; font-family: monospace; font-size: 13px;">${currentActiveRunWeatherStr}</span>`;
        } else {
            currentActiveRunWeatherStr = null;
        }
        
        box.innerHTML = `
            <span class="info-date-desktop" style="color:var(--text-main); font-weight:bold;">${dateFull}</span>
            <span class="info-date-mobile" style="display:none; color:var(--text-main); font-weight:bold;">${dateShort}</span>
            <span class="info-distance-wrap">&nbsp;&nbsp;&middot;&nbsp;&nbsp;${dist} km</span>
            ${weatherHtml}
        `;
    }
}

function renderRunCharts(run, chartsData) {
    const totalSecs = parseMovingTime(run.moving_time);
    if (!totalSecs || totalSecs <= 0) return;

    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    const accentColor = localStorage.getItem('accentColor') || '#e93342';
    const textColor = theme === 'light' ? '#6b7280' : '#888';
    const gridColor = theme === 'light' ? '#f3f4f6' : '#2a2a2a';

    let interval = 1800;
    if (totalSecs <= 1800) interval = 300; 
    else if (totalSecs <= 3600) interval = 900; 
    else if (totalSecs <= 7200) interval = 1800; 
    else interval = 3600; 

    const xAxisConfig = {
        type: 'value',
        min: 0,
        max: totalSecs,
        interval: interval,
        splitLine: { show: false },
        axisLabel: {
            color: textColor,
            formatter: val => {
                const m = Math.floor(val / 60);
                const s = Math.floor(val % 60).toString().padStart(2, '0');
				return m;
            }
        }
    };

    const gridConfig = { top: 10, right: 10, bottom: 20, left: 40 };

    if (chartsData.pace && chartsData.pace.data) {
        if (!paceChartInstance) paceChartInstance = echarts.init(document.getElementById('pace-chart'));
        const pData = chartsData.pace.data;
        const paceSeriesData = pData.map((val, i) => [ (i / (pData.length - 1)) * totalSecs, val ]);
        
        paceChartInstance.setOption({
            grid: gridConfig,
            tooltip: {
                trigger: 'axis',
                formatter: params => {
                    const val = params[0].value[1];
                    const m = Math.floor(val / 60);
                    const s = Math.floor(val % 60).toString().padStart(2, '0');
                    return `配速: ${m}'${s}" /km`;
                }
            },
            xAxis: xAxisConfig,
            yAxis: {
                type: 'value',
                inverse: true,
                min: 'dataMin', 
                max: function (value) {
                    return value.max > 600 ? 600 : null;
                }, 
                splitLine: { lineStyle: { color: gridColor } },
                axisLabel: {
                    color: textColor,
                    formatter: val => `${Math.floor(val/60)}'${Math.floor(val%60).toString().padStart(2,'0')}"`
                }
            },
            series: [{
                type: 'line',
                showSymbol: false,
                smooth: true,
                lineStyle: { width: 2, color: accentColor },
                itemStyle: { color: accentColor },
                data: paceSeriesData
            }]
        }, true);
    }

    if (chartsData.hr && chartsData.hr.data) {
        if (!hrChartInstance) hrChartInstance = echarts.init(document.getElementById('hr-chart'));
        const hData = chartsData.hr.data;
        const hrSeriesData = hData.map((val, i) => [ (i / (hData.length - 1)) * totalSecs, val ]);
        
        hrChartInstance.setOption({
            grid: gridConfig,
            tooltip: {
                trigger: 'axis',
                formatter: params => `心率: ${Math.round(params[0].value[1])} bpm`
            },
            xAxis: xAxisConfig,
            yAxis: {
                type: 'value',
                min: 30,
                max: 210,
                splitLine: { lineStyle: { color: gridColor } },
                axisLabel: { color: textColor }
            },
            series: [{
                type: 'line',
                showSymbol: false,
                smooth: true,
                lineStyle: { width: 2, color: '#f87171' },
                itemStyle: { color: '#f87171' },
                data: hrSeriesData
            }]
        }, true);
    }
}

function fetchRunDetails(run) {
    if (!run || !run.run_id) return;
    currentActiveRunId = run.run_id;
    
    fetch(`https://run.linwn.net/data/details/${run.run_id}.json`)
        .then(res => {
            if (!res.ok) throw new Error('Run details response failed.');
            return res.json();
        })
        .then(detail => {
            if (currentActiveRunId === run.run_id && detail) {
                if (detail.weather) {
                    updateMapInfoBox('single', run, detail.weather);
                }
                if (detail.charts) {
                    renderRunCharts(run, detail.charts);
                }
            }
        })
        .catch(err => console.error('Fetch run details failed:', err));
}

function clearMediaMarkers() {
    if (currentMediaMarkers.length > 0) {
        currentMediaMarkers.forEach(m => m.remove());
        currentMediaMarkers = [];
    }
    const btn = document.getElementById('media-btn');
    if (btn) btn.style.display = 'none';
    currentMediaData = null;
}

async function fetchMediaForRun(run) {
    if (!run || !run.run_id) return;
    clearMediaMarkers(); 

    try {
        const res = await fetch(`https://workerrunapi.linwn.net/api/media/${run.run_id}`);
        if (!res.ok) return;
        const data = await res.json();

        if (data && data.media && data.media.length > 0) {
            currentMediaData = data.media;
            document.getElementById('media-btn').style.display = 'block';

            data.media.forEach((item, index) => {
                if (item.location && item.location.lat && item.location.lng) {
                    const el = document.createElement('div');
                    el.className = 'media-marker-icon';

                    if (item.type === 'video') {
                        el.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
                    } else {
                        el.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="3.2"/><path d="M9 2L7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z"/></svg>';
                    }

                    el.onclick = (e) => {
                        e.stopPropagation();
                        openRunMediaGallery(index);
                    };

                    const marker = new maplibregl.Marker({element: el})
                        .setLngLat([item.location.lng, item.location.lat])
                        .addTo(map);
                    currentMediaMarkers.push(marker);
                }
            });
        }
    } catch (err) {
        console.error('Fetch media failed:', err);
    }
}

function openRunMediaGallery(startIndex = 0) {
    if (!currentMediaData || currentMediaData.length === 0) return;

    const dynamicElements = currentMediaData.map(item => {
        let mediaObj = {
            src: item.url,
            thumb: item.url
        };
        if (item.description) {
            mediaObj.subHtml = `<p style="font-size: 14px; text-align: center;">${item.description}</p>`;
        }
        if (item.type === 'video') {
            mediaObj.video = {"source": [{"src": item.url, "type": "video/mp4"}]};
            mediaObj.thumb = ""; 
        }
        return mediaObj;
    });

    const dummyContainer = document.createElement('div');
    const gallery = lightGallery(dummyContainer, {
        dynamic: true,
        plugins: [lgVideo],
        dynamicEl: dynamicElements,
        speed: 500,
        download: false
    });

    dummyContainer.addEventListener('lgAfterClose', () => {
        gallery.destroy(true);
    });

    gallery.openGallery(startIndex);
}

function calculateSummaries() {
    const now = new Date();
    const currentYear = now.getFullYear().toString();
    const currentMonth = `${currentYear}-${(now.getMonth() + 1).toString().padStart(2, '0')}`;
    const lastYearPrefix = (now.getFullYear() - 1).toString();
    
    let lmYear = now.getFullYear();
    let lmMonth = now.getMonth(); 
    if (lmMonth === 0) { lmMonth = 12; lmYear--; }
    const lastMonthPrefix = `${lmYear}-${lmMonth.toString().padStart(2, '0')}`;
    
    const sameDayMD = `${(now.getMonth() + 1).toString().padStart(2, '0')}-${now.getDate().toString().padStart(2, '0')}`;
    const sameDayD = now.getDate().toString().padStart(2, '0');

    let totalDist = 0, totalSeconds = 0, totalRunsCount = allRuns.length;
    let yearlyDist = 0, yearlySeconds = 0, yearlyRunsCount = 0, lastYearSamePeriodDist = 0;
    let monthlyDist = 0, monthlySeconds = 0, monthlyRunsCount = 0, lastMonthSamePeriodDist = 0;

    allRuns.forEach(run => {
        const distKm = (run.distance || 0) / 1000;
        const seconds = parseMovingTime(run.moving_time);
        const dateStr = run.start_date_local || "";

        totalDist += distKm;
        totalSeconds += seconds;

        if (dateStr.startsWith(currentYear)) {
            yearlyDist += distKm;
            yearlySeconds += seconds;
            yearlyRunsCount++;
        }
        if (dateStr.startsWith(lastYearPrefix)) {
            if (dateStr.substring(5, 10) <= sameDayMD) lastYearSamePeriodDist += distKm;
        }
        if (dateStr.startsWith(currentMonth)) {
            monthlyDist += distKm;
            monthlySeconds += seconds;
            monthlyRunsCount++;
        }
        if (dateStr.startsWith(lastMonthPrefix)) {
            if (dateStr.substring(8, 10) <= sameDayD) lastMonthSamePeriodDist += distKm;
        }
    });

    document.getElementById('total-distance').innerHTML = `${totalDist.toFixed(2)} <span>/ ${GOAL_TOTAL} km</span>`;
    document.getElementById('total-progress').style.width = `${Math.min(100, (totalDist / GOAL_TOTAL) * 100)}%`;
    document.getElementById('total-runs').innerText = totalRunsCount;
    document.getElementById('total-duration').innerText = formatHoursMins(totalSeconds);

    document.getElementById('yearly-dist').innerHTML = `${yearlyDist.toFixed(2)} <span>/ ${GOAL_YEARLY} km</span>`;
    document.getElementById('yearly-progress').style.width = `${Math.min(100, (yearlyDist / GOAL_YEARLY) * 100)}%`;
    document.getElementById('yearly-runs').innerText = yearlyRunsCount;
    document.getElementById('yearly-duration').innerText = formatHoursMins(yearlySeconds);
    
    const yearlyVs = yearlyDist - lastYearSamePeriodDist;
    const yearlyVsContainer = document.getElementById('yearly-vs-container');
    yearlyVsContainer.className = "stat-row left-aligned compare-info " + (yearlyVs >= 0 ? "trend-up" : "trend-down");
    yearlyVsContainer.innerHTML = `${yearlyVs >= 0 ? '↗' : '↘'} ${Math.abs(yearlyVs).toFixed(0)} km vs 去年同期`;

    document.getElementById('monthly-dist').innerHTML = `${monthlyDist.toFixed(2)} <span>/ ${GOAL_MONTHLY} km</span>`;
    document.getElementById('monthly-progress').style.width = `${Math.min(100, (monthlyDist / GOAL_MONTHLY) * 100)}%`;
    document.getElementById('monthly-runs').innerText = monthlyRunsCount;
    document.getElementById('monthly-duration').innerText = formatHoursMins(monthlySeconds);

    const monthlyVs = monthlyDist - lastMonthSamePeriodDist;
    const monthlyVsContainer = document.getElementById('monthly-vs-container');
    monthlyVsContainer.className = "stat-row left-aligned compare-info " + (monthlyVs >= 0 ? "trend-up" : "trend-down");
    monthlyVsContainer.innerHTML = `${monthlyVs >= 0 ? '↗' : '↘'} ${Math.abs(monthlyVs).toFixed(0)} km vs 上月同期`;
}

function processAndRenderRuns(data) {
    allRuns = data;
    allRuns.sort((a, b) => new Date(b.start_date_local.replace(/-/g, '/')) - new Date(a.start_date_local.replace(/-/g, '/')));
    allRuns.forEach(run => {
        if (run.summary_polyline) {
            try { run._cachedLatlngs = polyline.decode(run.summary_polyline); } catch (err) { run._cachedLatlngs = []; }
        } else { run._cachedLatlngs = []; }
    });       
    calculateSummaries();
    if (!map) initMap(); 		

    renderRecent4Weeks();
    renderMonthlyMileageChart();
    
    applyFilters();
}

async function fetchData() {
    const URL = 'https://run.linwn.net/data/activities_tagged.json';
    try {
        const cache = await caches.open('run-data-cache');
        const cachedResponse = await cache.match(URL);
        if (cachedResponse) {
            const cachedData = await cachedResponse.json();
            processAndRenderRuns(cachedData);
            handleHashRoute(); 
			//if (pageId === 'heatmap') renderHeatmapView();
        }
        const response = await fetch(URL);
        if (response.ok) {
            const responseToCache = response.clone(); 
            const freshData = await response.json();
            if (!cachedResponse || freshData.length !== allRuns.length) {
                await cache.put(URL, responseToCache); 
                processAndRenderRuns(freshData);
                handleHashRoute(); 
                
                if (isPredictionLoaded) updatePredictionPage();
                if (racesRendered) renderRaceCards();
				if (pageId === 'heatmap') renderHeatmapView();
            }
        }
    } catch (error) { console.error('Data loading failed:', error); }
}

function calculatePace(speedMs) {
    if (!speedMs) return "-";
    const secPerKm = 1000 / speedMs;
    return `${Math.floor(secPerKm / 60)}'${Math.floor(secPerKm % 60).toString().padStart(2, '0')}"`;
}

function getNameByTime(dateStr) {
    if (!dateStr) return "日常跑步";
    const parts = dateStr.split(' ');
    if (parts.length < 2) return "日常跑步";
    const hour = parseInt(parts[1].split(':')[0], 10);
    if (hour >= 4 && hour < 10) return "晨间跑步";
    if (hour >= 10 && hour < 14) return "上午跑步";
    if (hour >= 14 && hour < 17) return "午后跑步";
    if (hour >= 17 && hour < 20) return "傍晚跑步";
    return "夜间跑步";
}

function formatDuration(timeStr) {
    if (!timeStr) return "0:00:00";
    if (typeof timeStr === 'number') {
        const h = Math.floor(timeStr / 3600);
        const m = Math.floor((timeStr % 3600) / 60).toString().padStart(2, '0');
        const s = Math.floor(timeStr % 60).toString().padStart(2, '0');
        return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
    }
    return timeStr.split('.')[0];
}

// ==========================================================================
// 1. 新增: Recent 4 Weeks 日历矩阵
// ==========================================================================
function renderRecent4Weeks() {
    const grid = document.getElementById('recent-4weeks-grid');
    if (!grid) return;
    grid.innerHTML = '';

    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = today.getMonth();
    const currentDate = today.getDate();
    
    // 找到本周的周日 (如果为0则是周日，1是周一)
    let dayOfWeek = today.getDay();
    let daysToSunday = dayOfWeek === 0 ? 0 : 7 - dayOfWeek;
    
    const endOfWeek = new Date(currentYear, currentMonth, currentDate + daysToSunday);
    endOfWeek.setHours(23, 59, 59, 999);

    // 往前推4周共28天
    const startDate = new Date(endOfWeek);
    startDate.setDate(endOfWeek.getDate() - 27);
    startDate.setHours(0, 0, 0, 0);

    // 汇总每天跑量和对应记录
    const dailyData = {};
    allRuns.forEach(run => {
        if (!run.start_date_local) return;
        const dateStr = run.start_date_local.substring(0, 10);
        if (!dailyData[dateStr]) {
            dailyData[dateStr] = { dist: 0, runs: [] };
        }
        dailyData[dateStr].dist += (run.distance || 0) / 1000;
        dailyData[dateStr].runs.push(run);
    });

    const accent = localStorage.getItem('accentColor') || '#e93342';
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

    for (let i = 0; i < 28; i++) {
        const cellDate = new Date(startDate);
        cellDate.setDate(startDate.getDate() + i);

        const y = cellDate.getFullYear();
        const m = String(cellDate.getMonth() + 1).padStart(2, '0');
        const d = String(cellDate.getDate()).padStart(2, '0');
        const dateStr = `${y}-${m}-${d}`;

        const cell = document.createElement('div');
        cell.className = 'recent-4w-cell';
        if (dateStr === todayStr) {
            cell.classList.add('today');
        }

        const data = dailyData[dateStr];
        if (data && data.dist > 0) {
            const dist = data.dist;
            cell.innerHTML = dist.toFixed(1) + '&nbsp;<span class="hide-for-mobile">km</span>';
            
            // 背景色按跑量分深浅层次
            if (dist > 0 && dist < 10) {
                cell.style.backgroundColor = 'rgb(39 39 42)';
                cell.style.color = (theme === 'light') ? '#000' : 'rgb(212 212 216)';
            } else if (dist >= 10 && dist < 20) {
                cell.style.backgroundColor = 'rgb(82 82 91)';
                cell.style.color = 'rgb(212 212 216)';
            } else {
                cell.style.backgroundColor = 'rgb(127 29 29)';
                cell.style.color = 'rgb(212 212 216)';
            }

            // 点击日历格子的互动逻辑
            cell.addEventListener('click', () => {
                const mainRun = data.runs[0];
                highlightRunInTable(mainRun.run_id);
                renderMap(data.runs);
                updateMapInfoBox('single', mainRun);
                fetchRunDetails(mainRun);
                fetchMediaForRun(mainRun);
            });
        } else {
            cell.classList.add('empty');
            cell.innerText = '0';
        }

        grid.appendChild(cell);
    }
}
// ==========================================================================
// 3. 新增: 历史长条跑量热力图 (Heatmap)
// ==========================================================================
function renderHeatmapView() {
    const container = document.getElementById('heatmap-container');
    if (!container) return;
    container.innerHTML = '';

    // 【新增】判断是否为手机移动端（通常屏幕宽度小于等于 768px）
    const isMobile = window.innerWidth <= 768;
    const prevBtn = document.getElementById('heatmap-prev');

    if (isMobile) {
        // 手机端：一屏只渲染当前选中的那一年
        const block = createYearlyHeatmapBlock(targetHeatmapYear);
        container.appendChild(block);
		prevBtn.disabled = targetHeatmapYear <= firstRunDate.getFullYear();
		prevBtn.style.opacity = targetHeatmapYear <= firstRunDate.getFullYear() ? "0.3" : "1"; 
    } else {
        // 电脑端：保持原样，并排渲染最近 4 年
        for (let i = 3; i >= 0; i--) {
            const yearToRender = targetHeatmapYear - i;
            const block = createYearlyHeatmapBlock(yearToRender);
            container.appendChild(block);
        }
		prevBtn.disabled = targetHeatmapYear <= firstRunDate.getFullYear()+3;
		prevBtn.style.opacity = targetHeatmapYear <= firstRunDate.getFullYear()+3 ? "0.3" : "1"; 
    }
   
    // 更新“下一个”按钮状态（阻止切入未来没有数据的年份）
    const nextBtn = document.getElementById('heatmap-next');
    const currentYear = new Date().getFullYear();
    nextBtn.disabled = targetHeatmapYear >= currentYear;
    nextBtn.style.opacity = targetHeatmapYear >= currentYear ? "0.3" : "1";
}

function createYearlyHeatmapBlock(year) {
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';

    // 找出这一年的所有跑步数据并按日期聚合
    const dailyData = {};
    let yearlyDist = 0;
    let yearlyRunsCount = 0;
	let runs_below10k = 0;
	let runs_below20k = 0;
	let runs_above20k = 0;

    allRuns.forEach(run => {
        if (!run.start_date_local) return;
        if (run.start_date_local.startsWith(year.toString())) {
            const dateStr = run.start_date_local.substring(0, 10);
            if (!dailyData[dateStr]) {
                dailyData[dateStr] = { dist: 0, runs: [] };
            }
            dailyData[dateStr].dist += (run.distance || 0) / 1000;
            dailyData[dateStr].runs.push(run);
            yearlyDist += (run.distance || 0) / 1000;
            yearlyRunsCount++;
			if (run.distance > 20000) {runs_above20k ++;}
			else if (run.distance > 10000) { runs_below20k ++;}
			else {runs_below10k ++;}
        }
    });

    // 计算日历起止范围：包含当年 1 月 1 日所在周的周一，到 12 月 31 日所在周的周日
    const startDate = new Date(year, 0, 1);
    const dayOfWeekStart = startDate.getDay();
    const offsetStart = dayOfWeekStart === 0 ? 6 : dayOfWeekStart - 1; // 转换为：周一=0, 周日=6
    startDate.setDate(startDate.getDate() - offsetStart);

    const endDate = new Date(year, 11, 31);
    const dayOfWeekEnd = endDate.getDay();
    const offsetEnd = dayOfWeekEnd === 0 ? 0 : 7 - dayOfWeekEnd; // 周日结束
    endDate.setDate(endDate.getDate() + offsetEnd);

    const totalDays = Math.round((endDate - startDate) / (1000 * 60 * 60 * 24));

    // 创建区块 DOM
    const block = document.createElement('div');
    block.className = 'heatmap-year-block';

    block.innerHTML = `
		<div class="heatmap-year-header">
			<div class="heatmap-year-title">${year}</div>
			<div>
				<div><span style="font-weight:bold; color:var(--text-main);">${yearlyDist.toFixed(1)}</span> km</div>
				<div class="heatmap-legend">
					<div class="item"><span class="dot blue"></span>< 10k: ${runs_below10k} 次</div>
					<div class="item"><span class="dot yellow"></span>< 20k: ${runs_below20k} 次</div>
					<div class="item"><span class="dot red"></span>≥ 20k: ${runs_above20k} 次</div>
				</div>
			</div>
		</div>
        <div class="heatmap-body">
            <div class="heatmap-month-labels"></div>
            <div class="heatmap-grid"></div>
        </div>
        <div class="heatmap-footer">
            <span style="font-weight:bold; color:var(--text-main);">${yearlyRunsCount}</span> 次活动<br/>
            <span style="font-weight:bold; color:var(--text-main);">${yearlyDist.toFixed(1)}</span> km
        </div>
    `;

    const grid = block.querySelector('.heatmap-grid');
    const labelsContainer = block.querySelector('.heatmap-month-labels');

    let currentMonth = -1;
    const cellHeight = 24; 
    const cellGap = 3;     
    const rowHeight = cellHeight + cellGap;

    for (let i = 0; i < totalDays; i++) {
        const cellDate = new Date(startDate);
        cellDate.setDate(startDate.getDate() + i);

        const m = cellDate.getMonth();
        const dateStr = `${cellDate.getFullYear()}-${String(m + 1).padStart(2, '0')}-${String(cellDate.getDate()).padStart(2, '0')}`;

        const cell = document.createElement('div');
        cell.className = 'heatmap-cell';

        // 左侧月份标签逻辑：只要该周的第一天或者遇到新的月份
        const weekIndex = Math.floor(i / 7);
        if (cellDate.getFullYear() === year && m !== currentMonth) {
            currentMonth = m;
            const label = document.createElement('div');
            label.className = 'heatmap-month-label';
            label.innerText = `${m + 1}月`;
            // 根据所在的行（周）计算 top 偏移量
            label.style.top = `${weekIndex * rowHeight}px`;
            labelsContainer.appendChild(label);
        }

        // 数据填充与颜色渲染
        if (cellDate.getFullYear() !== year) {
            cell.classList.add('empty'); // 不属于当年的补齐天数，不可见
        } else {
            const data = dailyData[dateStr];
            if (data && data.dist > 0) {
                const dist = data.dist;
                cell.title = `${dateStr} : ${dist.toFixed(1)} km`; // 原生提示框
				cell.innerHTML = `${dist.toFixed(1)} <small>km</small>`;
                if (dist > 0 && dist < 10) {
                    cell.style.backgroundColor = 'rgb(7 89 133)';
                } else if (dist >= 10 && dist < 20) {
                    cell.style.backgroundColor = 'rgb(202 138 4)';
                } else {
                    cell.style.backgroundColor = 'rgb(227 25 55)';
                }

                cell.addEventListener('dblclick', () => {
                    const mainRun = data.runs[0];
                    window.location.hash = '#dashboard';
                    setTimeout(() => {
                        highlightRunInTable(mainRun.run_id);
                        renderMap(data.runs);
                        updateMapInfoBox('single', mainRun);
                        fetchRunDetails(mainRun);
                        fetchMediaForRun(mainRun);
                    }, 100);
                });
            } else {
                // 无跑步记录的灰色底格
                cell.style.backgroundColor = 'var(--progress-bg)';
				cell.className += " empty";
            }
        }
        grid.appendChild(cell);
    }

    return block;
}
// ==========================================================================
// 2. 新增: 按月跑量 Bar 图 (Monthly Mileage)
// ==========================================================================
function renderMonthlyMileageChart() {
    const chartDom = document.getElementById('monthly-mileage-chart');
    if (!chartDom) return;

    if (!monthlyMileageChartInstance) {
        monthlyMileageChartInstance = echarts.init(chartDom);
        monthlyMileageChartInstance.on('click', function(params) {
            const clickedMonth = String(params.dataIndex + 1).padStart(2, '0');
            // 点击同一个月则取消选中，否则设为当前筛选月
            if (currentMonthFilter === clickedMonth) {
                currentMonthFilter = null;
            } else {
                currentMonthFilter = clickedMonth;
            }
            updateMonthlyChartColors();
            applyFilters();
        });
    }

	const monthlyData = new Array(12).fill(0);
    
    let targetYear = currentYearFilter;
    if (targetYear === 'all') {
        // 如果是 All，取最新的一条记录的年份；如果没数据，兜底使用当前自然年
        targetYear = allRuns.length > 0 ? allRuns[0].start_date_local.substring(0, 4) : new Date().getFullYear().toString();
    }
    
    allRuns.forEach(run => {
        if (!run.start_date_local) return;
        const y = run.start_date_local.substring(0, 4);
        const m = parseInt(run.start_date_local.substring(5, 7), 10) - 1;
        
        // 只统计与 targetYear 匹配的数据
        if (y === targetYear) {
            monthlyData[m] += (run.distance || 0) / 1000;
        }
    });

    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    const textColor = theme === 'light' ? '#6b7280' : '#888';
    const gridColor = theme === 'light' ? '#f3f4f6' : '#2a2a2a';
    const accent = localStorage.getItem('accentColor') || '#e93342';

    const option = {
        title: {
            text: `${targetYear}`,
            textStyle: { color: textColor, fontSize: 24, fontWeight: 'bold' },
            left: 'right',
            top: 0
        },
        grid: { top: 30, right: 20, bottom: 30, left: 20 },
        tooltip: { trigger: 'axis', formatter: '{b}: {c} km' },
        xAxis: {
            type: 'category',
            data: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
            axisLabel: { color: textColor },
            axisLine: { show: false, lineStyle: { color: gridColor } },
			axisTick: { show: false }
        },
        yAxis: {
			show: false,
            type: 'value',
            splitLine: { lineStyle: { color: gridColor } },
            axisLabel: { color: textColor }
        },
        series: [{
            type: 'bar',
            data: monthlyData.map((val, idx) => {
                const mStr = String(idx + 1).padStart(2, '0');
                return {
                    value: val.toFixed(1),
                    itemStyle: {
                        color: currentMonthFilter === mStr ? accent : '#555555' // 灰底色搭配主色强调
                    }
                };
            }),
            barMaxWidth: 30,
            itemStyle: { borderRadius: [4, 4, 0, 0] }
        }]
    };

    monthlyMileageChartInstance.setOption(option);
}

function updateMonthlyChartColors() {
    if (!monthlyMileageChartInstance) return;
    const option = monthlyMileageChartInstance.getOption();
    const accent = localStorage.getItem('accentColor') || '#e93342';
    const seriesData = option.series[0].data.map((item, idx) => {
        const mStr = String(idx + 1).padStart(2, '0');
        return {
            value: item.value,
            itemStyle: { color: currentMonthFilter === mStr ? accent : '#555555' }
        };
    });
    monthlyMileageChartInstance.setOption({ series: [{ data: seriesData }] });
}

// ==========================================================================
// 过滤及高亮联动逻辑
// ==========================================================================

function highlightRunInTable(runId) {
    const index = filteredRuns.findIndex(r => r.run_id === runId);
    if (index !== -1) {
        const targetPage = Math.floor(index / itemsPerPage) + 1;
        
        if (currentPage !== targetPage) {
            currentPage = targetPage;
            renderTable(false); 
        } else {
            document.querySelectorAll('#table-body tr').forEach(r => r.classList.remove('active-row'));
        }
        
        const row = document.querySelector(`#table-body tr[data-run-id="${runId}"]`);
        if (row) {
            row.classList.add('active-row');
            //row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
}

function renderTable(resetHighlights = true) {
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = '';

    const startIdx = (currentPage - 1) * itemsPerPage;
    const endIdx = startIdx + itemsPerPage;
    const pageData = filteredRuns.slice(startIdx, endIdx);

    pageData.forEach((run, index) => {
        const distKm = (run.distance / 1000).toFixed(2);
        const pace = calculatePace(run.average_speed);
        const duration = formatDuration(run.moving_time);
        const name = (run.race && run.race.race_name) ? run.race.race_name : (run.name || getNameByTime(run.start_date_local));
        const hr = run.average_heartrate ? Math.round(run.average_heartrate) : '-';

        const tr = document.createElement('tr');
        tr.setAttribute('data-run-id', run.run_id || '');
        tr.innerHTML = `
            <td style="width: 160px; white-space: nowrap;color: var(--text-muted);">${run.start_date_local || ''}</td>
            <td>${name}</td>
            <td class="font-mono"><span class="font-mono">${distKm}</span> <span class="unit font-mono">km</span></td>
            <td class="font-mono">${duration}</td>
            <td class="font-mono">${pace}</td>
            <td class="font-mono">${hr}</td>
        `;
        tr.style.cursor = 'pointer';
        tr.style.animationDelay = `${index * 40}ms`;

        tr.addEventListener('click', () => {
            document.querySelectorAll('#table-body tr').forEach(r => r.classList.remove('active-row'));
            tr.classList.add('active-row');
            
            renderMap(run);
            updateMapInfoBox('single', run); 
            fetchRunDetails(run);
			fetchMediaForRun(run);
        });
        tbody.appendChild(tr);
    });

    const totalPages = Math.ceil(filteredRuns.length / itemsPerPage) || 1;
    document.getElementById('page-info').innerText = `Page ${currentPage} of ${totalPages}`;
    
    const showEnd = Math.min(endIdx, filteredRuns.length);
    const showStart = filteredRuns.length === 0 ? 0 : startIdx + 1;
    document.getElementById('showing-text').innerText = `Showing ${showStart}-${showEnd} of ${filteredRuns.length}`;
}

function applyFilters(skipMapRender = false) {
    let tempRuns = [];
    
    // 年份判断
    if (currentYearFilter === 'all') {
        tempRuns = [...allRuns];
    } else {
        tempRuns = allRuns.filter(run => run.start_date_local && run.start_date_local.startsWith(currentYearFilter));
    }

    // 新增：按月份判断 (来自点击柱状图联动)
    if (currentMonthFilter) {
        tempRuns = tempRuns.filter(run => run.start_date_local && run.start_date_local.substring(5, 7) === currentMonthFilter);
    }

    if (currentTypeFilter === 'race') {
        filteredRuns = tempRuns.filter(run => run.race != null);
    } else if (currentTypeFilter === 'track') {
        filteredRuns = tempRuns.filter(run => run.subtype === 'track');
    } else if (currentTypeFilter === 'locgz') {
        filteredRuns = tempRuns.filter(run => run.location_country && run.location_country.includes('广州'));
    } else if (currentTypeFilter === 'locmm') {
        filteredRuns = tempRuns.filter(run => run.location_country && run.location_country.includes('茂名'));
    } else if (currentTypeFilter === 'locother') {
        filteredRuns = tempRuns.filter(run => (!run.location_country || !run.location_country.includes('广州') && !run.location_country.includes('茂名')));
    } else if (currentTypeFilter === 'fastest10Runs') {
        filteredRuns = tempRuns.filter(run => run.distance > 100).sort((a, b) => b.average_speed - a.average_speed).slice(0, 10);
    } else if (currentTypeFilter === 'longest10Runs') {
        filteredRuns = tempRuns.filter(run => run.distance > 100).sort((a, b) => b.distance - a.distance).slice(0, 10);
    } else if (currentTypeFilter === 'onThisDay') {
        filteredRuns = tempRuns.filter(run => run.start_date_local && run.start_date_local.includes(`${(new Date().getMonth() + 1).toString().padStart(2, '0')}-${new Date().getDate().toString().padStart(2, '0')}`));
    } else if (currentTypeFilter === 'media') {
        filteredRuns = tempRuns.filter(run => mediaRunIds.includes(String(run.run_id)));
    } else {
        filteredRuns = tempRuns;
    }

    if (!skipMapRender) {
        renderMap(filteredRuns);
    }
    
    let filterDist = 0;
    let filterSecs = 0;
    filteredRuns.forEach(r => {
        filterDist += (r.distance || 0) / 1000;
        filterSecs += parseMovingTime(r.moving_time);
    });
    updateMapInfoBox('summary', { dist: filterDist, runs: filteredRuns.length, seconds: filterSecs });

    currentPage = 1;
    renderTable();
}

// ==========================================================================
// AI Summary Logic (保持独立分析页面逻辑)
// ==========================================================================
let aiIndexList = [];
let currentAiIndex = 0; 
let aiIndexLoaded = false;

async function loadAiIndex() {
    if (aiIndexLoaded) return;
    try {
        const res = await fetch('https://run.linwn.net/data/summary/index.json');
        if (res.ok) {
            aiIndexList = await res.json();
            aiIndexLoaded = true;
            
            if (aiIndexList.length > 0) {
                currentAiIndex = 0; 
                loadAiReport(currentAiIndex);
            } else {
                document.getElementById('ai-markdown-content').innerHTML = '<p style="color: var(--text-muted);">暂无分析报告。</p>';
            }
        } else {
            throw new Error("Index fetch failed");
        }
    } catch (err) {
        console.error("Failed to load AI index", err);
        document.getElementById('ai-markdown-content').innerHTML = '<p style="color: var(--accent-color);">无法加载分析报告列表，请确保后台已生成数据。</p>';
    }
}

async function loadAiReport(index) {
    if (index < 0 || index >= aiIndexList.length) return;
    currentAiIndex = index;
    
    const fileInfo = aiIndexList[index];
    document.getElementById('ai-date-badge').innerText = fileInfo.date;
    document.getElementById('ai-page-info').innerText = `${index + 1} / ${aiIndexList.length}`;

    document.getElementById('ai-btn-prev').disabled = (index >= aiIndexList.length - 1); 
    document.getElementById('ai-btn-next').disabled = (index <= 0); 

    document.getElementById('ai-markdown-content').innerHTML = '<p style="color: var(--text-muted);">加载报告内容中...</p>';
    
    try {
        const res = await fetch(`https://run.linwn.net/data/summary/${fileInfo.report}`);
        if (res.ok) {
            const mdText = await res.text();
            let container = document.getElementById('ai-markdown-content');
            container.innerHTML = marked.parse(mdText);
            container.querySelectorAll('table').forEach(table => {
                const wrapper = document.createElement('div');
                wrapper.className = 'table-wrapper';
            
                table.parentNode.insertBefore(wrapper, table);
                wrapper.appendChild(table);
            });              
            window.scrollTo(0, 0);
        } else {
            document.getElementById('ai-markdown-content').innerHTML = '<p style="color: var(--accent-color);">加载报告内容失败。</p>';
        }
    } catch (err) {
        document.getElementById('ai-markdown-content').innerHTML = '<p style="color: var(--accent-color);">加载报告内容发生异常。</p>';
    }
}

// --- Events binding ---

document.getElementById('ai-btn-prev').addEventListener('click', () => {
    if (currentAiIndex < aiIndexList.length - 1) loadAiReport(currentAiIndex + 1); 
});

document.getElementById('ai-btn-next').addEventListener('click', () => {
    if (currentAiIndex > 0) loadAiReport(currentAiIndex - 1); 
});

document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        if(e.target.id === 'settings-close' || e.target.id === 'settings-save' || e.target.id === 'pb-toggle-btn' || e.target.id === 'ai-btn-prev' || e.target.id === 'ai-btn-next') return;

        if (e.target.hasAttribute('data-year')) {
            document.querySelectorAll('#year-filters .filter-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            
            currentYearFilter = e.target.getAttribute('data-year');
            currentMonthFilter = null; // 切换年份重置月份
            
            renderMonthlyMileageChart(); // 更新图表年份重载数据
            applyFilters();
        }
    });
});

document.getElementById('type-filter').addEventListener('change', async (e) => {
    currentTypeFilter = e.target.value;
    if (currentTypeFilter === 'media' && !isMediaRunIdsLoaded) {
        e.target.disabled = true; 
        await loadMediaRunIds();
        e.target.disabled = false;
    }
    applyFilters();
});

document.getElementById('prev-page').addEventListener('click', () => {
    if (currentPage > 1) { currentPage--; renderTable(); }
});

document.getElementById('next-page').addEventListener('click', () => {
    const totalPages = Math.ceil(filteredRuns.length / itemsPerPage);
    if (currentPage < totalPages) { currentPage++; renderTable(); }
});
document.getElementById('heatmap-prev').addEventListener('click', () => {
    targetHeatmapYear--;
    renderHeatmapView();
});

document.getElementById('heatmap-next').addEventListener('click', () => {
    targetHeatmapYear++;
    renderHeatmapView();
});
// Map - Chart Toggle Event
document.getElementById('toggle-map-chart-btn').addEventListener('click', () => {
    const chartsContainer = document.getElementById('run-charts-container');
    const mapContainer = document.getElementById('map');
    
    if (chartsContainer.style.display === 'none') {
        chartsContainer.style.display = 'flex';
        mapContainer.style.display = 'none';
        if (paceChartInstance) paceChartInstance.resize();
        if (hrChartInstance) hrChartInstance.resize();
    } else {
        chartsContainer.style.display = 'none';
        mapContainer.style.display = 'block';
        if (map) map.resize();
    }
});


// ==========================================================================
// Hash Routing, Page Navigation & Media Gallery
// ==========================================================================
let lgInstance = null; 

function handleHashRoute() {
    const hash = window.location.hash || '#dashboard';
    const rawPath = hash.replace('#', '');
    const pathParts = rawPath.split('/');
    const pageId = pathParts[0] === '' ? 'dashboard' : pathParts[0];
    const subId = pathParts[1] || null;

    if (allRuns.length === 0 && pageId !== 'dashboard' && pageId !== 'settings'  && pageId !== 'ai-summary') {
        return; 
    }

    window.scrollTo(0, 0); 

    document.getElementById('dashboard-page').style.display = pageId === 'dashboard' ? 'flex' : 'none';
    document.getElementById('settings-page').style.display = pageId === 'settings' ? 'flex' : 'none';
    document.getElementById('prediction-page').style.display = pageId === 'prediction' ? 'flex' : 'none';
    document.getElementById('ai-page').style.display = pageId === 'ai-summary' ? 'flex' : 'none';
    document.getElementById('races-page').style.display = pageId === 'races' ? 'flex' : 'none';
	document.getElementById('heatmap-page').style.display = pageId === 'heatmap' ? 'flex' : 'none';
    
    document.querySelectorAll('.desktop-menu a').forEach(a => a.classList.remove('active'));
    document.querySelectorAll('.mobile-menu-item').forEach(a => a.classList.remove('active'));
    
    if (pageId === 'dashboard') {
        document.getElementById('menu-home').classList.add('active');
        document.getElementById('mobile-menu-home').classList.add('active');
        if (map) setTimeout(() => map.resize(), 100); 
		if (monthlyMileageChartInstance) setTimeout(() => monthlyMileageChartInstance.resize(), 100);
    } else if (pageId === 'heatmap') {
		document.getElementById('menu-heatmap').classList.add('active');
		document.getElementById('mobile-menu-heatmap').classList.add('active');
		if (allRuns.length > 0) renderHeatmapView();
	} else if (pageId === 'ai-summary') {
        document.getElementById('menu-ai').classList.add('active');
        document.getElementById('mobile-menu-ai').classList.add('active');
        loadAiIndex(); 
    } else if (pageId === 'settings') {
        document.getElementById('menu-settings').classList.add('active');
        document.getElementById('mobile-menu-settings').classList.add('active');
        
        const theme = localStorage.getItem('theme') || 'dark';
        document.querySelector(`input[name="setting-theme"][value="${theme}"]`).checked = true;
        const color = localStorage.getItem('accentColor') || '#e93342';
        const colorRadio = document.querySelector(`input[name="setting-color"][value="${color}"]`);
        if (colorRadio) colorRadio.checked = true;
        const centerMode = localStorage.getItem('mapCenterMode') || 'A';
        document.querySelector(`input[name="setting-map-center"][value="${centerMode}"]`).checked = true;
        document.getElementById('setting-lng').value = localStorage.getItem('mapCenterLng') || '113.3';
        document.getElementById('setting-lat').value = localStorage.getItem('mapCenterLat') || '23.1';
        document.getElementById('settings-custom-coords').style.display = (centerMode === 'B') ? 'flex' : 'none';

    } else if (pageId === 'prediction') {
        document.getElementById('menu-prediction').classList.add('active');
        document.getElementById('mobile-menu-prediction').classList.add('active');
        if (allRuns.length > 0) updatePredictionPage();
        if (tandaTrendChartInstance) setTimeout(() => tandaTrendChartInstance.resize(), 100);
        if (tandaProgChartInstance) setTimeout(() => tandaProgChartInstance.resize(), 100);
    } else if (pageId === 'races') {
        document.getElementById('menu-races').classList.add('active');
        document.getElementById('mobile-menu-races').classList.add('active');
        if (!pbLoaded) loadAndRenderPB();
        if (!racesRendered && allRuns.length > 0) renderRaceCards();
        
        if (subId) {
            openRaceDetail(subId);
        } else {
            document.getElementById('race-detail-view').style.display = 'none';
            document.getElementById('races-list-view').style.display = 'block';
            if (lgInstance) { lgInstance.destroy(true); lgInstance = null; }
        }
    }
}

window.addEventListener('hashchange', handleHashRoute);

document.querySelectorAll('input[name="setting-map-center"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        document.getElementById('settings-custom-coords').style.display = (e.target.value === 'B') ? 'flex' : 'none';
    });
});

document.getElementById('settings-close').addEventListener('click', () => {
    window.location.hash = '#dashboard';
});

document.getElementById('settings-save').addEventListener('click', () => {
    const theme = document.querySelector('input[name="setting-theme"]:checked').value;
    const color = document.querySelector('input[name="setting-color"]:checked').value;
    const centerMode = document.querySelector('input[name="setting-map-center"]:checked').value;
    const lng = document.getElementById('setting-lng').value;
    const lat = document.getElementById('setting-lat').value;

    localStorage.setItem('theme', theme);
    localStorage.setItem('accentColor', color);
    localStorage.setItem('mapCenterMode', centerMode);
    localStorage.setItem('mapCenterLng', lng);
    localStorage.setItem('mapCenterLat', lat);

    applyThemeAndColor(theme, color);
    applyFilters(); 
    
    window.location.hash = '#dashboard';
});

// ==========================================================================
// Tanda Prediction & ECharts Logic
// ==========================================================================
function calculateTandaTime(weeklyDist, avgPaceSec) {
    if (!weeklyDist || !avgPaceSec || weeklyDist <= 0 || avgPaceSec <= 0) return null;
    const pm = 17.1 + 140.0 * Math.exp(-0.0053 * weeklyDist) + 0.55 * avgPaceSec;
    return 42.195 * pm; 
}

function formatPredictionTime(seconds) {
    if (!seconds) return '-';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
}

function formatPredictionPace(decimal) {
    const m = Math.floor(decimal);
    const s = Math.round((decimal - m) * 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

function formatLocalYYYYMMDD(dateObj) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function updatePredictionPage() {
    if (allRuns.length === 0) return;

    const rawRunData = allRuns.map(r => ({
        date: r.start_date_local,
        distance: (r.distance || 0) / 1000,
        duration: parseMovingTime(r.moving_time)
    })).filter(r => r.distance > 0 && r.duration > 0);

    const today = new Date();
    today.setHours(0,0,0,0);
    const dayMs = 24 * 3600 * 1000;
    
    let rollDist = 0, rollTime = 0;
    rawRunData.forEach(r => {
        const dMs = new Date(r.date.replace(/-/g, '/')).getTime();
        if (today.getTime() - dMs <= 56 * dayMs && today.getTime() - dMs >= 0) {
            rollDist += r.distance;
            rollTime += r.duration;
        }
    });

    const avgWeeklyDistanceKm = (rollDist / 56) * 7;
    const avgPaceSecKm = rollDist > 0 ? rollTime / rollDist : 0;
    const predictedTimeSeconds = calculateTandaTime(avgWeeklyDistanceKm, avgPaceSecKm);

    document.getElementById('prediction-loading').style.display = 'none';
    document.getElementById('prediction-content').style.display = 'block';

    document.getElementById('pred-weekly-dist').innerText = avgWeeklyDistanceKm.toFixed(1);

    if (avgPaceSecKm > 0) {
        const paceMin = Math.floor(avgPaceSecKm / 60);
        const paceSec = Math.floor(avgPaceSecKm % 60).toString().padStart(2, '0');
        document.getElementById('pred-avg-pace').innerText = `${paceMin}'${paceSec}"`;
    } else {
        document.getElementById('pred-avg-pace').innerText = `-`;
    }

    if (predictedTimeSeconds && predictedTimeSeconds > 0) {
        document.getElementById('pred-marathon-time').innerText = formatPredictionTime(predictedTimeSeconds);
        document.getElementById('pred-marathon-time').style.fontSize = "28px";
    } else {
        document.getElementById('pred-marathon-time').innerText = "数据不足";
        document.getElementById('pred-marathon-time').style.fontSize = "20px";
    }

    renderTandaCharts(rawRunData, today, dayMs);
    isPredictionLoaded = true;
}

function renderTandaCharts(rawRunData, today, dayMs) {
    const runsMap = new Map();
    rawRunData.forEach(run => {
        const dStr = run.date.substring(0, 10);
        if(!runsMap.has(dStr)) runsMap.set(dStr, []);
        runsMap.get(dStr).push(run);
    });

    const trendScatterData = []; 
    const trendLineData = [];    

    for (let i = 180; i >= 0; i--) {
        const targetDate = new Date(today.getTime() - i * dayMs);
        const targetDateStr = formatLocalYYYYMMDD(targetDate);
        
        const dayRuns = runsMap.get(targetDateStr) || [];
        if (dayRuns.length > 0) {
            let dDist = 0, dTime = 0;
            dayRuns.forEach(r => { dDist += r.distance; dTime += r.duration; });
            const dPace = dTime / dDist;
            const singleDayPred = calculateTandaTime(dDist * 7, dPace);
            if (singleDayPred) {
                trendScatterData.push([targetDateStr, singleDayPred]);
            }
        }

        let rollDist = 0, rollTime = 0;
        for (let j = 0; j < 56; j++) {
            const pastDateStr = formatLocalYYYYMMDD(new Date(targetDate.getTime() - j * dayMs));
            const pastRuns = runsMap.get(pastDateStr) || [];
            pastRuns.forEach(r => { rollDist += r.distance; rollTime += r.duration; });
        }
        
        if (rollDist > 0) {
            const rollPace = rollTime / rollDist;
            const rollPred = calculateTandaTime((rollDist / 56) * 7, rollPace);
            if (rollPred) {
                trendLineData.push([targetDateStr, rollPred]);
            }
        }
    }

    const contourSeries = [];
    const targetMarathonTimes = [
        { label: '2:45', sec: 9900 }, { label: '3:00', sec: 10800 },
        { label: '3:15', sec: 11700 }, { label: '3:30', sec: 12600 },
        { label: '3:45', sec: 13500 }, { label: '4:00', sec: 14400 },
        { label: '4:15', sec: 15300 }, { label: '4:30', sec: 16200 },
        { label: '4:45', sec: 17100 }
    ];

    targetMarathonTimes.forEach(target => {
        const pm = target.sec / 42.195;
        const lineData = [];
        for (let p = 3.5; p <= 7.5; p += 0.05) {
            const paceSec = p * 60;
            const val = (pm - 17.1 - 0.55 * paceSec) / 140.0;
            if (val > 0 && val < 1) { 
                const dailyDist = -Math.log(val) / (0.0053 * 7);
                if (dailyDist > 0 && dailyDist <= 40) { 
                    lineData.push([p, dailyDist]);
                }
            }
        }
        if (lineData.length > 0) {
            contourSeries.push({
                type: 'line',
                name: target.label,
                smooth: true,
                showSymbol: false,
                lineStyle: { type: 'dashed', color: '#555555', width: 1 },
                data: lineData,
                endLabel: { show: true, formatter: target.label, color: '#888' }
            });
        }
    });

    const recentScatterData = [];
    const progressionLineData = [];
    
    const recentRunDates = [];
    for (let i = 56; i >= 0; i--) {
        const dStr = formatLocalYYYYMMDD(new Date(today.getTime() - i * dayMs));
        if (runsMap.has(dStr)) recentRunDates.push({ date: dStr, daysAgo: i });
    }

    recentRunDates.forEach(runItem => {
        const dayRuns = runsMap.get(runItem.date);
        let dDist = 0, dTime = 0;
        dayRuns.forEach(r => { dDist += r.distance; dTime += r.duration; });
        const dPaceMin = (dTime / dDist) / 60;
        
        const opacity = Math.max(0.15, 1 - (runItem.daysAgo / 56));
        recentScatterData.push({
            value: [dPaceMin, dDist, runItem.date],
            itemStyle: { color: `rgba(180, 180, 180, ${opacity})` }
        });

        let rollDist = 0, rollTime = 0;
        const targetMs = new Date(runItem.date.replace(/-/g, '/')).getTime();
        for (let j = 0; j < 56; j++) {
            const pastDateStr = formatLocalYYYYMMDD(new Date(targetMs - j * dayMs));
            const pastRuns = runsMap.get(pastDateStr) || [];
            pastRuns.forEach(r => { rollDist += r.distance; rollTime += r.duration; });
        }
        if (rollDist > 0) {
            const rollPaceMin = (rollTime / rollDist) / 60;
            const rollDailyDist = rollDist / 56;
            
            progressionLineData.push({
                value: [rollPaceMin, rollDailyDist, runItem.date],
                itemStyle: {}
            });
        }
    });

    if (progressionLineData.length > 0) {
        progressionLineData[progressionLineData.length - 1].symbolSize = 6; 
    }

    if (!tandaTrendChartInstance) tandaTrendChartInstance = echarts.init(document.getElementById('tandaTrendChart'));
    if (!tandaProgChartInstance) tandaProgChartInstance = echarts.init(document.getElementById('tandaProgressionChart'));

    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    const accentHex = localStorage.getItem('accentColor') || '#e93342';
    
    const axisConfig = {
        splitLine: { lineStyle: { color: theme === 'light' ? '#f3f4f6' : '#2a2a2a' } },
        axisLine: { lineStyle: { color: theme === 'light' ? '#ccc' : '#666' } },
        axisLabel: { color: theme === 'light' ? '#6b7280' : '#888' }
    };

    tandaTrendChartInstance.setOption({
        grid: { top: 20, right: 30, bottom: 30, left: 60 },
        tooltip: {
            trigger: 'axis',
            backgroundColor: theme === 'light' ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.8)',
            textStyle: { color: theme === 'light' ? '#333' : '#fff' },
            formatter: params => {
                let html = `${params[0].value[0]}<br/>`;
                params.forEach(p => {
                    const seriesName = p.seriesName === '单日推演' ? '单日假设持续8周' : '实际近8周均值';
                    html += `${p.marker} ${seriesName}: <b>${formatPredictionTime(p.value[1])}</b><br/>`;
                });
                return html;
            }
        },
        xAxis: { type: 'time', ...axisConfig },
        yAxis: {
            type: 'value',
            scale: true,
            inverse: true, 
            axisLabel: { formatter: val => formatPredictionTime(val), color: axisConfig.axisLabel.color },
            splitLine: axisConfig.splitLine
        },
        series: [
            {
                name: '单日推演',
                type: 'scatter',
                symbolSize: 4,
                itemStyle: { color: theme === 'light' ? '#aaa' : '#555' },
                data: trendScatterData
            },
            {
                name: '近8周滚动推演',
                type: 'line',
                smooth: true,
                showSymbol: false,
                lineStyle: { width: 3, color: accentHex },
                data: trendLineData
            }
        ]
    }, true);

    tandaProgChartInstance.setOption({
        grid: { top: 30, right: 50, bottom: 40, left: 50 },
        tooltip: {
            backgroundColor: theme === 'light' ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.8)',
            textStyle: { color: theme === 'light' ? '#333' : '#fff' },
            formatter: params => {
                if(params.seriesName === '单日散点' || params.seriesName === '8周均值路径') {
                    const dateStr = params.value[2];
                    const pace = formatPredictionPace(params.value[0]);
                    const dist = params.value[1].toFixed(2);
                    return `<b>${dateStr}</b><br/>${params.seriesName}<br/>配速: ${pace} /km<br/>跑量: ${dist} km`;
                }
                return `${params.seriesName} 完赛等高线`;
            }
        },
        xAxis: {
            type: 'value',
            name: '配速 (min/km)',
            nameLocation: 'middle',
            nameGap: 25,
            min: 3.5,
            max: 7.5,
            axisLabel: { formatter: val => formatPredictionPace(val), color: axisConfig.axisLabel.color },
            splitLine: { show: false },
            axisLine: axisConfig.axisLine
        },
        yAxis: {
            type: 'value',
            name: '日均跑量 (km)',
            scale: true,
            axisLabel: { color: axisConfig.axisLabel.color },
            splitLine: axisConfig.splitLine,
            axisLine: axisConfig.axisLine
        },
        dataZoom: [
            { type: 'inside', xAxisIndex: [0], filterMode: 'none' },
            { type: 'inside', yAxisIndex: [0], filterMode: 'none' },				
        ],
        series: [
            ...contourSeries,
            {
                name: '单日散点',
                type: 'scatter',
                symbolSize: 6,
                data: recentScatterData
            },
            {
                name: '8周均值路径',
                type: 'line',
                symbol: 'circle',
                symbolSize: 1,
                itemStyle: { color: accentHex },
                lineStyle: { width: 1, color: accentHex },
                data: progressionLineData
            }
        ]
    }, true);
}

window.addEventListener('resize', () => {
    if (tandaTrendChartInstance) tandaTrendChartInstance.resize();
    if (tandaProgChartInstance) tandaProgChartInstance.resize();
    if (monthlyMileageChartInstance) monthlyMileageChartInstance.resize();
    if (detailMapInstance && document.getElementById('race-detail-view').style.display === 'block') detailMapInstance.resize();
    if (paceChartInstance && document.getElementById('run-charts-container').style.display === 'flex') paceChartInstance.resize();
    if (hrChartInstance && document.getElementById('run-charts-container').style.display === 'flex') hrChartInstance.resize();
});

// ==========================================================================
// Races Records & Personal Best Logic
// ==========================================================================

// PB Logic
const TARGET_DISTANCES = {
    1000: "1公里",
    3000: "3公里",
    5000: "5公里",
    10000: "10公里",
    21097.5: "半程马拉松",
    42195: "全程马拉松"
};

function formatPace(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}'${s.toString().padStart(2, '0')}"`;
}

function formatDateStr(dateNum) {
    const dStr = dateNum.toString();
    if (dStr.length !== 8) return dStr;
    return `${dStr.substring(0,4)}-${dStr.substring(4,6)}-${dStr.substring(6,8)}`;
}

async function loadAndRenderPB() {
    if (pbLoaded) return;
    try {
        const response = await fetch('https://run.linwn.net/data/pb.json');
        if (!response.ok) throw new Error('Network response failed');
        const pbData = await response.json();
        
        const pbGrid = document.getElementById('pb-grid');
        pbGrid.innerHTML = ''; 
        
        const filteredPBs = pbData
            .filter(item => TARGET_DISTANCES[item.distance])
            .sort((a, b) => a.distance - b.distance);

        if (filteredPBs.length === 0) {
            pbGrid.innerHTML = '<p style="color: var(--text-muted);">暂无个人最佳数据</p>';
            return;
        }

        filteredPBs.forEach(pb => {
            const card = document.createElement('div');
            card.className = 'pb-card';
            
            const distanceName = TARGET_DISTANCES[pb.distance];
            const timeStr = formatDuration(pb.record);
            const paceStr = formatPace(pb.avgPace);
            const dateStr = formatDateStr(pb.happenDay);

            card.innerHTML = `
                <div class="pb-distance">${distanceName}</div>
                <div class="pb-time">${timeStr}</div>
                <div class="pb-meta">
                    <span class="pb-pace">${paceStr}</span>
                    <span>${dateStr}</span>
                </div>
            `;
            pbGrid.appendChild(card);
        });
        pbLoaded = true;
    } catch (error) {
        console.error('Failed to load PB data:', error);
        document.getElementById('pb-grid').innerHTML = '<p style="color: var(--text-muted);">无法加载个人最佳数据</p>';
    }
}

// Race List & Details Logic
function renderRaceCards() {
    allRaceActivities = allRuns
        .filter(a => a.race && a.race.race_name)
        .sort((a, b) => new Date(b.start_date_local.replace(/-/g,'/')) - new Date(a.start_date_local.replace(/-/g,'/')));

    document.getElementById('races-summary').innerText = `共参赛 ${allRaceActivities.length} 场`;
    const grid = document.getElementById('races-grid');
    grid.innerHTML = '';

    allRaceActivities.forEach(activity => {
        const race = activity.race;
        const dateStr = activity.start_date_local.substring(0, 10);
        
        const card = document.createElement('div');
        card.className = 'race-card';
        card.onclick = () => { window.location.hash = `#races/${activity.run_id}`; };
        
        card.innerHTML = `
            <div class="race-card-header">
                <h3 class="race-card-title">${race.race_name}</h3>
                <span class="race-badge">${race.race_type}</span>
            </div>
            <div class="race-card-time">${race.official_time || '--:--:--'}</div>
            <div class="race-card-meta">
                <span>${dateStr}</span>
                <span>${(activity.distance / 1000).toFixed(2)} km</span>
            </div>
        `;
        grid.appendChild(card);
    });
    racesRendered = true;
}

function openRaceDetail(runId) {
    const activity = allRaceActivities.find(a => String(a.run_id) === String(runId));
    if (!activity) return;

    const race = activity.race;

    document.getElementById('detail-race-name').innerText = race.race_name;
    document.getElementById('detail-race-type').innerText = race.race_type;
    document.getElementById('detail-race-date').innerText = activity.start_date_local.substring(0, 16);
    document.getElementById('detail-race-loc').innerText = activity.location_country || '未知地点';
    
    document.getElementById('detail-official-time').innerText = race.official_time || '--:--:--';
    document.getElementById('detail-distance').innerText = (activity.distance / 1000).toFixed(2);
    
    document.getElementById('detail-pace').innerText = calculatePace(activity.average_speed);
    document.getElementById('detail-hr').innerText = activity.average_heartrate ? Math.round(activity.average_heartrate) : '-';

    const mediaContainer = document.getElementById('detail-media-gallery');
    mediaContainer.innerHTML = '';
    
    if (lgInstance) {
        lgInstance.destroy(true);
        lgInstance = null;
    }

    if (race.medias && race.medias.length > 0) {
        race.medias.forEach(item => {
            const url = item.mediaUrl;
            const isVideo = url.match(/\.(mp4|webm|mov)$/i);
            
            const wrapper = document.createElement('a');
            wrapper.className = 'media-gallery-link';
            
            if (isVideo) {
                wrapper.setAttribute('data-video', `{"source": [{"src":"${url}", "type":"video/mp4"}]}`);
                const video = document.createElement('video');
                video.src = url;
                video.className = 'media-item';
                wrapper.appendChild(video);
            } else {
                wrapper.setAttribute('data-src', url);
                const img = document.createElement('img');
                img.src = url;
                img.className = 'media-item';
                wrapper.appendChild(img);
            }
            mediaContainer.appendChild(wrapper);
        });
        
        lgInstance = lightGallery(mediaContainer, {
            plugins: [lgVideo],
            speed: 500,
            selector: '.media-gallery-link',
            download: false 
        });
    } else {
        mediaContainer.innerHTML = '<p style="color: var(--text-muted); font-size: 14px;">暂无多媒体资料</p>';
    }

    document.getElementById('races-list-view').style.display = 'none';
    document.getElementById('race-detail-view').style.display = 'block';

    renderDetailMap(activity);
}

function closeRaceDetail() {
    window.location.hash = '#races';
}

function renderDetailMap(run) {
    if (!run || !run._cachedLatlngs || run._cachedLatlngs.length === 0) {
        document.getElementById('race-detail-map').innerHTML = '<div style="padding: 20px; color: var(--text-muted);">暂无路线数据</div>';
        return;
    }

    const geojsonCoords = run._cachedLatlngs.map(coord => [coord[1], coord[0]]);
    const geojsonData = { 'type': 'FeatureCollection', 'features': [{
        'type': 'Feature',
        'geometry': { 'type': 'LineString', 'coordinates': geojsonCoords }
    }]};

    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    const mapStyle = theme === 'light' ? 'https://tiles.openfreemap.org/styles/positron' : 'https://run.linwn.net/dark_matter.json';
    const accentColor = localStorage.getItem('accentColor') || '#e93342';

    if (!detailMapInstance) {
        detailMapInstance = new maplibregl.Map({
            container: 'race-detail-map',
            style: mapStyle,
            attributionControl: false,
            cooperativeGestures: true,
        });
        
        detailMapInstance.on('load', () => {
            detailMapInstance.addSource('detail-route-source', { 'type': 'geojson', 'data': geojsonData });
            detailMapInstance.addLayer({
                'id': 'detail-route-layer',
                'type': 'line',
                'source': 'detail-route-source',
                'layout': { 'line-join': 'round', 'line-cap': 'round' },
                'paint': { 'line-color': accentColor, 'line-width': 4 }
            });
            fitDetailMapBounds(geojsonCoords);
        });
    } else {
        if (detailMapInstance.getSource('detail-route-source')) {
            detailMapInstance.getSource('detail-route-source').setData(geojsonData);
        }
        if (detailMapInstance.getLayer('detail-route-layer')) {
            detailMapInstance.setPaintProperty('detail-route-layer', 'line-color', accentColor);
        }
        detailMapInstance.resize(); 
        fitDetailMapBounds(geojsonCoords);
    }
}

function fitDetailMapBounds(coords) {
    if (coords.length > 0) {
        const pointsLong = coords.map(p => p[0]);
        const pointsLat = coords.map(p => p[1]);
        const bounds = [
            [Math.min(...pointsLong), Math.min(...pointsLat)],
            [Math.max(...pointsLong), Math.max(...pointsLat)]
        ];
        detailMapInstance.fitBounds(bounds, { padding: 40, animate: false });
    }
}

document.getElementById('pb-toggle-btn').addEventListener('click', function() {
    const pbGrid = document.getElementById('pb-grid');
    
    if (pbGrid.style.display === 'none') {
        pbGrid.style.display = 'grid';
        this.innerText = '收起';
        this.classList.add('active'); 
    } else {
        pbGrid.style.display = 'none';
        this.innerText = '展开';
        this.classList.remove('active');
    }
});

document.getElementById('media-btn').addEventListener('click', () => {
    openRunMediaGallery(0);
});
const toggleBtn = document.getElementById('activity-toggle');
const section = document.querySelector('.activity-section');
const btnText = toggleBtn.querySelector('span');

toggleBtn.addEventListener('click', function() {
    section.classList.toggle('expanded');
});
// 监听屏幕尺寸变化，保证横竖屏切换时自动调整单年/多年视图
window.addEventListener('resize', () => {
    if (window.location.hash === '#heatmap' && allRuns.length > 0) {
        renderHeatmapView();
    }
});

fetchData();
