import qrcode

PAYLOAD = "LT-BLANK-V1"
q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=1, border=0)
q.add_data(PAYLOAD)
q.make(fit=True)
m = q.get_matrix()
n = len(m)

fills = []
for y, row in enumerate(m):
    x = 0
    while x < n:
        if row[x]:
            x2 = x
            while x2 + 1 < n and row[x2 + 1]:
                x2 += 1
            fills.append(f"\\fill ({x},{n-1-y}) rectangle ({x2+1},{n-y});")
            x = x2 + 1
        x += 1

head = f"""% СГЕНЕРИРОВАНО, правится не здесь — см. README, раздел «QR».
%
% Содержимое постоянное: {PAYLOAD}. Одинаковое на всех бланках пачки, про
% ученика и работу не говорит ничего — только «это наш бланк такой-то версии».
% Ради этого он и стоит: тысяча листов живёт в кабинете год, и когда бланк
% сменится, старые и новые будут лежать вперемешку, а читать их надо по разной
% геометрии. Плюс страница, на которой его нет вовсе, — вообще не наш лист.
%
% Матрица вписана готовой: она никогда не меняется, а пакета qrcode в образе
% нет. Уровень коррекции H — читается, если испорчено до 30% модулей.
% Размер: {n}x{n} модулей; аргумент команды — сторона на бумаге.
\\newcommand{{\\blankqr}}[1]{{%
\\begin{{tikzpicture}}[x=#1/{n},y=#1/{n}]
"""
tail = "\\end{tikzpicture}}\n"
open("/w/qr_v1.tex", "w", encoding="utf-8").write(head + "\n".join(fills) + "\n" + tail)
print(f"{n}x{n} модулей, версия {q.version}, заливок {len(fills)}")
