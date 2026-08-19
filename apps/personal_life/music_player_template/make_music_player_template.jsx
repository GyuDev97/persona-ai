/*
  여기까지만 하자 - Vertical Music Player Template
  After Effects 2022+ / JSX
  Run: File > Scripts > Run Script File...

  This creates an editable 1080 x 1920 composition using the supplied MP3
  and cover image. Change the two paths below when moving this script.
*/
(function () {
    app.beginUndoGroup("Create Music Player Template");

    // ===== EDIT THESE TWO PATHS IF NEEDED =====
    var audioFile = new File("C:/Users/bgpoi/OneDrive/Desktop/여기까지만 하자.mp3");
    var coverFile = new File("C:/Users/bgpoi/OneDrive/Desktop/여기까지만 하자.jpeg");
    var songTitle = "우리 여기까지만 하자";
    var artistName = "by @gyulabs";
    var duration = 323; // 05:23 (read from the supplied MP3)
    // The first sung line begins at 00:14.00 (provided timing).
    // Remaining lines are distributed through the supplied 05:23 audio.
    var lyricStart = 14.00;
    var firstLineDuration = 3.25;
    var lineDuration = 5.01;
    var lyricLines = [
        "늦은 밤 시계 소리만 들리고", "식어 버린 커피만 남아 있어", "평소처럼 네 옆에 앉아 있는데", "오늘은 왜 이렇게 멀게 느껴져",
        "괜찮다는 말을 먼저 꺼내면", "정말 괜찮아질 줄 알았어", "하지만 떨리는 네 목소리에", "이미 끝이 와 있었나 봐",
        "어디부터 어긋난 건지", "이제 와 묻지는 않을게", "사랑했던 그 순간까지", "없던 일로 하진 말아 줘",
        "우리 여기까지만 하자", "더 아프기 전에 끝내자", "너를 붙잡고 싶은 이 마음도", "오늘까지만 참아 볼게",
        "사랑했다고 말하지 마", "그 말 들으면 또 무너질 테니", "돌아서서 문을 닫는 그때까지", "아무 말 없이 가 줘",
        "현관에 남은 너의 작은 신발", "냉장고에 붙어 있는 사진", "내일이면 하나씩 사라질 텐데", "왜 난 아무것도 못 버리겠어",
        "너 없이도 괜찮을 거라고", "몇 번이고 나를 속여 봐도", "익숙했던 네 이름 하나에", "가슴이 또 무너져 내려",
        "붙잡으면 더 아플 거란 걸", "나도 너무 잘 알고 있어", "그래도 오늘이 마지막이면", "조금만 더 있어 줘",
        "우리 여기까지만 하자", "더 아프기 전에 끝내자", "너를 붙잡고 싶은 이 마음도", "오늘까지만 참아 볼게",
        "사랑했다고 말하지 마", "그 말 들으면 또 무너질 테니", "돌아서서 문을 닫는 그때까지", "아무 말 없이 가 줘",
        "사실은 가지 말라고", "한 번쯤 붙잡고 싶었어", "아무 일도 없던 것처럼", "다시 시작하자고",
        "하지만 네가 행복하다면", "그게 내가 아니어도", "오늘까지만 아파하고", "내가 먼저 놓아줄게",
        "우리 여기까지만 하자", "그래 정말 여기서 끝내자", "평생 너만 사랑할 것 같던 내가", "이제 너를 보내야 하나 봐",
        "잘 지내란 말은 못 하겠어", "아직 그렇게 괜찮진 않아서", "네가 없는 내일이 두려워도", "이젠 혼자 견뎌야 하니까",
        "우리 여기까지만 하자", "마지막으로 안아도 될까", "다시는 돌아갈 수 없다 해도", "오늘만은 울어도 되잖아",
        "우리 여기까지만 하자", "오늘 여기까지만"
    ];
    // ===========================================

    if (!audioFile.exists || !coverFile.exists) {
        alert("음원 또는 커버 이미지 파일을 찾을 수 없습니다.\n스크립트 상단의 audioFile / coverFile 경로를 수정한 뒤 다시 실행하세요.");
        app.endUndoGroup();
        return;
    }

    function importFootage(file) {
        var io = new ImportOptions(file);
        return app.project.importFile(io);
    }
    function setColor(prop, rgb) { prop.setValue(rgb); }
    function addText(comp, name, value, x, y, size, color, justification, opacity) {
        var l = comp.layers.addText(value);
        l.name = name;
        var td = l.property("Source Text").value;
        td.font = "NotoSansKR-Regular";
        td.fontSize = size;
        td.fillColor = color;
        td.applyFill = true;
        td.justification = justification || ParagraphJustification.CENTER_JUSTIFY;
        l.property("Source Text").setValue(td);
        l.property("Transform").property("Position").setValue([x, y]);
        if (opacity !== undefined) l.property("Transform").property("Opacity").setValue(opacity);
        return l;
    }
    function addSolid(comp, name, color, w, h, x, y, opacity) {
        var l = comp.layers.addSolid(color, name, w, h, 1, duration);
        l.property("Transform").property("Position").setValue([x, y]);
        l.property("Transform").property("Opacity").setValue(opacity === undefined ? 100 : opacity);
        return l;
    }
    function addLine(comp, name, x1, x2, y, thickness, color, opacity) {
        var s = comp.layers.addShape(); s.name = name;
        var g = s.property("Contents").addProperty("ADBE Vector Group");
        var p = g.property("Contents").addProperty("ADBE Vector Shape - Group");
        var sh = new Shape(); sh.vertices = [[x1, y], [x2, y]]; sh.closed = false; p.property("Path").setValue(sh);
        var st = g.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
        st.property("Color").setValue(color); st.property("Stroke Width").setValue(thickness);
        s.property("Transform").property("Opacity").setValue(opacity === undefined ? 100 : opacity);
        return s;
    }
    function addCircle(comp, name, x, y, radius, color, opacity) {
        var s = comp.layers.addShape(); s.name = name;
        var g = s.property("Contents").addProperty("ADBE Vector Group");
        var e = g.property("Contents").addProperty("ADBE Vector Shape - Ellipse");
        e.property("Size").setValue([radius * 2, radius * 2]);
        var f = g.property("Contents").addProperty("ADBE Vector Graphic - Fill"); f.property("Color").setValue(color);
        s.property("Transform").property("Position").setValue([x, y]);
        s.property("Transform").property("Opacity").setValue(opacity === undefined ? 100 : opacity);
        return s;
    }
    function animateProgress(comp, fill, handle, timeText) {
        var pathProperty = fill.property("Contents").property(1).property("Contents").property(1).property("Path");
        function progressPath(endX) {
            var path = new Shape();
            path.vertices = [[150, 1572], [endX, 1572]];
            path.closed = false;
            return path;
        }
        pathProperty.setValueAtTime(0, progressPath(150));
        pathProperty.setValueAtTime(duration, progressPath(930));
        handle.property("Transform").property("Position").setValueAtTime(0, [150, 1572]);
        handle.property("Transform").property("Position").setValueAtTime(duration, [930, 1572]);
        timeText.property("Source Text").expression = "var total = Math.floor(time); var minutes = Math.floor(total / 60); var seconds = total % 60; ('0' + minutes).slice(-2) + ':' + ('0' + seconds).slice(-2);";
    }
    function addKaraokeLyrics(comp, lines, start, firstEach, each) {
        var activeY = 1196, lineGap = 71;
        function timeAt(index) {
            if (index <= 0) return start;
            if (index >= lines.length) return duration;
            return start + firstEach + (index - 1) * each;
        }
        for (var i = 0; i < lines.length; i++) {
            var l = addText(comp, "LYRIC " + ("0" + (i + 1)).slice(-2), lines[i], 540, activeY, 38, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 0);
            l.inPoint = Math.max(0, timeAt(Math.max(0, i - 3)));
            l.outPoint = Math.min(duration, timeAt(i + 4));
            var pos = l.property("Transform").property("Position");
            var op = l.property("Transform").property("Opacity");
            for (var current = Math.max(0, i - 3); current <= Math.min(lines.length - 1, i + 3); current++) {
                var distance = Math.abs(i - current);
                pos.setValueAtTime(timeAt(current), [540, activeY + (i - current) * lineGap]);
                op.setValueAtTime(timeAt(current), distance === 0 ? 100 : (distance === 1 ? 65 : (distance === 2 ? 42 : 0)));
            }
        }
    }

    if (!app.project) app.newProject();
    var audio = importFootage(audioFile);
    var cover = importFootage(coverFile);
    var comp = app.project.items.addComp("01_MUSIC_PLAYER_MASTER", 1080, 1920, 1, duration, 30);
    comp.bgColor = [0.035, 0.045, 0.04];

    // Soft, dark album-art background.
    var bg = comp.layers.add(cover); bg.name = "BG - blurred cover";
    bg.property("Transform").property("Position").setValue([540, 960]);
    bg.property("Transform").property("Scale").setValue([215, 215]);
    bg.property("Transform").property("Opacity").setValue(28);
    bg.property("Transform").property("Scale").setValueAtTime(0, [210, 210]);
    bg.property("Transform").property("Scale").setValueAtTime(duration, [230, 230]);
    bg.Effects.addProperty("ADBE Gaussian Blur 2").property("Blurriness").setValue(90);
    addSolid(comp, "BG - dark wash", [0.025, 0.035, 0.03], 1080, 1920, 540, 960, 69);

    // Header (edit these text layers in AE).
    var title = addText(comp, "TXT - song title", songTitle, 540, 315, 61, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 100);
    var artist = addText(comp, "TXT - artist", artistName, 540, 380, 30, [0.78, 0.78, 0.76], ParagraphJustification.CENTER_JUSTIFY, 100);
    title.property("Transform").property("Opacity").setValueAtTime(0, 0);
    title.property("Transform").property("Opacity").setValueAtTime(0.65, 100);
    artist.property("Transform").property("Opacity").setValueAtTime(0.2, 0);
    artist.property("Transform").property("Opacity").setValueAtTime(0.9, 100);

    // Cover precomp makes image replacement simple: Alt-drag a new image onto the layer.
    var coverComp = app.project.items.addComp("02_COVER_ART", 620, 620, 1, duration, 30);
    var coverLayer = coverComp.layers.add(cover); coverLayer.name = "REPLACE - cover image";
    coverLayer.property("Transform").property("Position").setValue([310, 310]);
    var sx = 620 / cover.width * 100, sy = 620 / cover.height * 100;
    var sc = Math.max(sx, sy); coverLayer.property("Transform").property("Scale").setValue([sc, sc]);
    // Rounded alpha track matte. This avoids version-dependent third-party effects.
    var coverMatte = coverComp.layers.addShape(); coverMatte.name = "MATTE - rounded corners";
    var matteGroup = coverMatte.property("Contents").addProperty("ADBE Vector Group");
    var matteRect = matteGroup.property("Contents").addProperty("ADBE Vector Shape - Rect");
    matteRect.property("Size").setValue([620, 620]);
    matteRect.property("Roundness").setValue(42);
    var matteFill = matteGroup.property("Contents").addProperty("ADBE Vector Graphic - Fill");
    matteFill.property("Color").setValue([1, 1, 1]);
    coverMatte.property("Transform").property("Position").setValue([310, 310]);
    coverLayer.trackMatteType = TrackMatteType.ALPHA;
    var coverMain = comp.layers.add(coverComp); coverMain.name = "COVER - replace in 02_COVER_ART";
    coverMain.property("Transform").property("Position").setValue([540, 698]);
    coverMain.property("Transform").property("Opacity").setValueAtTime(0, 0);
    coverMain.property("Transform").property("Opacity").setValueAtTime(0.8, 100);
    coverMain.property("Transform").property("Scale").setValueAtTime(0, [104, 104]);
    coverMain.property("Transform").property("Scale").setValueAtTime(2, [100, 100]);
    coverMain.property("Transform").property("Scale").setValueAtTime(duration, [104, 104]);

    addLine(comp, "Cover scan line", 230, 850, 710, 2, [1, 1, 1], 42);
    addText(comp, "TXT - cover index", "01  /  10", 540, 918, 18, [0.95, 0.95, 0.93], ParagraphJustification.CENTER_JUSTIFY, 90);

    // Full lyrics: five-line karaoke window; current line is bright, nearby lines are dimmed.
    addKaraokeLyrics(comp, lyricLines, lyricStart, firstLineDuration, lineDuration);

    // Progress bar, set to screenshot's 01:23 position. Animate Progress fill width for a full video.
    addLine(comp, "Progress - track", 150, 930, 1572, 5, [1, 1, 1], 35);
    var progress = addLine(comp, "Progress - fill (animate width)", 150, 392, 1572, 5, [1, 1, 1], 100);
    var progressHandle = addCircle(comp, "Progress - handle", 392, 1572, 13, [1, 1, 1], 100);
    var currentTime = addText(comp, "TXT - current time", "00:00", 100, 1577, 22, [0.95, 0.95, 0.93], ParagraphJustification.LEFT_JUSTIFY, 95);
    addText(comp, "TXT - duration", "05:23", 980, 1577, 22, [0.95, 0.95, 0.93], ParagraphJustification.RIGHT_JUSTIFY, 95);
    animateProgress(comp, progress, progressHandle, currentTime);

    // Controls are deliberately simple text symbols, so all assets remain self-contained.
    addText(comp, "CTRL - repeat", "↻", 140, 1708, 47, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 95);
    addText(comp, "CTRL - previous", "Ⅰ◀", 360, 1708, 43, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 100);
    addCircle(comp, "CTRL - play circle", 540, 1700, 78, [0.08, 0.09, 0.08], 12);
    addText(comp, "CTRL - pause", "Ⅱ", 540, 1712, 70, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 100);
    addText(comp, "CTRL - next", "▶Ⅰ", 720, 1708, 43, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 100);
    addText(comp, "CTRL - like", "♡", 940, 1708, 57, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 95);
    addText(comp, "TXT - playlist", "☷  재생목록", 190, 1840, 25, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 85);
    addText(comp, "TXT - lyrics menu", "▥  가사", 540, 1840, 25, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 85);
    addText(comp, "TXT - share", "⌯  공유", 870, 1840, 25, [1, 1, 1], ParagraphJustification.CENTER_JUSTIFY, 85);

    var audioLayer = comp.layers.add(audio); audioLayer.name = "AUDIO - 여기까지만 하자";
    audioLayer.startTime = 0;
    comp.openInViewer();
    alert("템플릿 생성 완료. 파일 > 다른 이름으로 저장으로 .aep 프로젝트를 저장하세요.");
    app.endUndoGroup();
}());
