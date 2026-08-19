/*
  Apply the exact SRT timings to an existing music-player AEP.
  1. Open the generated AEP and select 01_MUSIC_PLAYER_MASTER in the Project panel.
  2. File > Scripts > Run Script File... > this JSX file.
*/
(function () {
    app.beginUndoGroup("Apply SRT lyric timing");
    var srtFile = new File("C:/Users/bgpoi/OneDrive/Desktop/여기까지만_하자_lyrics.srt");
    if (!srtFile.exists) {
        alert("SRT 파일을 찾지 못했습니다. 스크립트 상단의 srtFile 경로를 확인하세요.");
        app.endUndoGroup();
        return;
    }
    function seconds(value) {
        var parts = value.replace(",", ".").split(":");
        return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
    }
    function parseSrt(file) {
        file.encoding = "UTF-8";
        file.open("r");
        var raw = file.read();
        file.close();
        var blocks = raw.replace(/\r/g, "").split("\n\n"), result = [];
        for (var i = 0; i < blocks.length; i++) {
            var lines = blocks[i].split("\n");
            if (lines.length < 3 || lines[1].indexOf("-->") < 0) continue;
            var range = lines[1].split("-->");
            result.push({ start: seconds(range[0].replace(/^\s+|\s+$/g, "")), end: seconds(range[1].replace(/^\s+|\s+$/g, "")), text: lines.slice(2).join("\r") });
        }
        return result;
    }
    function findMasterComp() {
        if (app.project.activeItem instanceof CompItem) return app.project.activeItem;
        for (var i = 1; i <= app.project.numItems; i++) {
            if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "01_MUSIC_PLAYER_MASTER") return app.project.item(i);
        }
        return null;
    }
    function addLyric(comp, name, text, y) {
        var layer = comp.layers.addText(text);
        layer.name = name;
        var style = layer.property("Source Text").value;
        style.font = "NotoSansKR-Regular";
        style.fontSize = 38;
        style.fillColor = [1, 1, 1];
        style.applyFill = true;
        style.justification = ParagraphJustification.CENTER_JUSTIFY;
        layer.property("Source Text").setValue(style);
        layer.property("Transform").property("Position").setValue([540, y]);
        return layer;
    }
    function animateProgress(comp) {
        var fill = comp.layer("Progress - fill (animate width)");
        var handle = comp.layer("Progress - handle");
        var timeText = comp.layer("TXT - current time");
        if (!fill || !handle) return;
        var pathProperty = fill.property("Contents").property(1).property("Contents").property(1).property("Path");
        function progressPath(endX) {
            var path = new Shape();
            path.vertices = [[150, 1572], [endX, 1572]];
            path.closed = false;
            return path;
        }
        pathProperty.setValueAtTime(0, progressPath(150));
        pathProperty.setValueAtTime(comp.duration, progressPath(930));
        handle.property("Transform").property("Position").setValueAtTime(0, [150, 1572]);
        handle.property("Transform").property("Position").setValueAtTime(comp.duration, [930, 1572]);
        if (timeText && timeText.property("Source Text").canSetExpression) {
            timeText.property("Source Text").expression = "var total = Math.floor(time); var minutes = Math.floor(total / 60); var seconds = total % 60; ('0' + minutes).slice(-2) + ':' + ('0' + seconds).slice(-2);";
        }
    }

    var cues = parseSrt(srtFile);
    var comp = findMasterComp();
    if (!comp || !cues.length) {
        alert("마스터 컴포지션 또는 SRT 가사를 찾지 못했습니다.");
        app.endUndoGroup();
        return;
    }
    // Remove the estimated lyrics only; all artwork, audio, and controls remain intact.
    for (var layerIndex = comp.numLayers; layerIndex >= 1; layerIndex--) {
        if (comp.layer(layerIndex).name.indexOf("LYRIC ") === 0) comp.layer(layerIndex).remove();
    }

    var activeY = 1196, lineGap = 71;
    for (var cueIndex = 0; cueIndex < cues.length; cueIndex++) {
        var cue = cues[cueIndex];
        var lyric = addLyric(comp, "LYRIC " + ("0" + (cueIndex + 1)).slice(-2), cue.text, activeY);
        lyric.inPoint = cues[Math.max(0, cueIndex - 3)].start;
        lyric.outPoint = cueIndex + 4 < cues.length ? cues[cueIndex + 4].start : Math.min(comp.duration, cue.end);
        var pos = lyric.property("Transform").property("Position");
        var opacity = lyric.property("Transform").property("Opacity");
        for (var current = Math.max(0, cueIndex - 3); current <= Math.min(cues.length - 1, cueIndex + 3); current++) {
            var distance = Math.abs(cueIndex - current);
            pos.setValueAtTime(cues[current].start, [540, activeY + (cueIndex - current) * lineGap]);
            opacity.setValueAtTime(cues[current].start, distance === 0 ? 100 : (distance === 1 ? 65 : (distance === 2 ? 42 : 0)));
        }
    }
    animateProgress(comp);
    alert(cues.length + "줄의 정확한 SRT 타이밍을 적용했습니다. Ctrl+S로 프로젝트를 저장하세요.");
    app.endUndoGroup();
}());
