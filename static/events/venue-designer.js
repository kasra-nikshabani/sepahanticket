/* Pure layout operations, shared by the UI and bounded-layout tests. */
(() => {
  const clone = value => JSON.parse(JSON.stringify(value));
  const limits = { sections: 8, rows: 60, columns: 80, positions: 5000 };
  const empty = () => ({ version: 1, stage: 'top', direction: 'rtl', sections: [] });
  const capacity = plan => plan.sections.reduce((sum, section) => sum + section.rows.reduce((total, row) => total + row.seats.filter(seat => seat !== null).length, 0), 0);
  const positions = plan => plan.sections.reduce((sum, section) => sum + section.rows.reduce((total, row) => total + row.seats.length, 0), 0);
  const build = ({ id, name, rows, seats, aisle = 0, width = 1, alignment = 'start', curvature = 0 }) => {
    if (!Number.isInteger(curvature) || Math.abs(curvature) > 100) throw new Error('انحنا باید بین منفی ۱۰۰ و ۱۰۰ باشد.');
    if (!['start', 'center', 'end'].includes(alignment)) throw new Error('چینش ردیف معتبر نیست.');
    if (!name.trim() || name.trim().length > 50) throw new Error('نام بخش را وارد کن؛ حداکثر ۵۰ نویسه.');
    if (!Number.isInteger(rows) || rows < 1 || rows > limits.rows) throw new Error('تعداد ردیف باید بین ۱ و ۶۰ باشد.');
    if (!Number.isInteger(seats) || seats < 1 || seats > limits.columns) throw new Error('تعداد صندلی باید بین ۱ و ۸۰ باشد.');
    if (!Number.isInteger(aisle) || aisle < 0 || aisle >= seats) throw new Error('محل راهرو را قبل از آخرین صندلی وارد کن، یا خالی بگذار.');
    if (aisle && (!Number.isInteger(width) || width < 1 || width > 5 || seats + width > limits.columns)) throw new Error('پهنای راهرو باید بین ۱ و ۵ باشد و مجموع جایگاه‌ها از ۸۰ بیشتر نشود.');
    const cells = Array.from({ length: seats }, (_, index) => index + 1);
    if (aisle) cells.splice(aisle, 0, ...Array(width).fill(null));
    return { id, name: name.trim(), rows: Array.from({ length: rows }, (_, index) => ({ number: index + 1, offset: 0, alignment, curvature, seats: [...cells] })) };
  };
  const validateSize = plan => {
    if (!plan || plan.version !== 1 || !['top', 'bottom'].includes(plan.stage) || !['rtl', 'ltr'].includes(plan.direction) || !Array.isArray(plan.sections)) throw new Error('قالب نقشه سالن معتبر نیست.');
    const ids = new Set();
    plan.sections.forEach(section => {
      if (!section || typeof section.id !== 'string' || !/^[a-zA-Z0-9_-]{1,40}$/.test(section.id) || ids.has(section.id) || typeof section.name !== 'string' || !section.name.trim() || section.name.length > 50 || !Array.isArray(section.rows) || section.rows.length > limits.rows) throw new Error('اطلاعات بخش سالن معتبر نیست.');
      ids.add(section.id);
      const numbers = new Set();
      section.rows.forEach(row => {
        if (!row || !Number.isInteger(row.curvature ?? 0) || Math.abs(row.curvature ?? 0) > 100) throw new Error('انحنای ردیف معتبر نیست.');
        if (!['start', 'center', 'end'].includes(row.alignment || 'start')) throw new Error('چینش ردیف معتبر نیست.');
        if (!row || !Number.isInteger(row.number) || row.number < 1 || row.number > 999 || numbers.has(row.number) || !Number.isInteger(row.offset) || row.offset < 0 || row.offset > 20 || !Array.isArray(row.seats) || row.seats.length < 1 || row.seats.length > limits.columns) throw new Error('اطلاعات ردیف سالن معتبر نیست.');
        numbers.add(row.number);
        const used = new Set();
        row.seats.forEach(seat => {
          if (seat === null) return;
          if (!Number.isInteger(seat) || seat < 1 || seat > 999 || used.has(seat)) throw new Error('شماره صندلی‌ها باید مثبت و یکتا باشد.');
          used.add(seat);
        });
      });
    });
    if (plan.sections.length > limits.sections || positions(plan) > limits.positions) throw new Error('حداکثر ۸ بخش و مجموعاً ۵۰۰۰ جایگاه مجاز است.');
    if (new Set(plan.sections.map(section => section.name)).size !== plan.sections.length) throw new Error('نام هر بخش باید متفاوت باشد.');
  };
  const toggle = (plan, id, rowNumber, position) => {
    const section = plan.sections.find(item => item.id === id);
    const row = section && section.rows.find(item => item.number === rowNumber);
    if (!row || position < 0 || position >= row.seats.length) return;
    if (row.seats[position] !== null) { row.seats[position] = null; return; }
    const used = new Set(row.seats.filter(value => value !== null));
    let label = (row.seats.slice(0, position).filter(value => value !== null).at(-1) || 0) + 1;
    while (used.has(label)) label += 1;
    if (label > 999) { label = 1; while (used.has(label)) label += 1; }
    row.seats[position] = label;
  };
  // A symmetric parabola includes aisle positions and does not alter seat identities.
  const curve = (curvature, index, count, step = 36) => {
    if (count <= 2) return { y: 0, angle: 0 };
    const height = curvature * .48;
    const x = 2 * index / (count - 1) - 1;
    return { y: Math.round(height * (1 - x * x)), angle: Math.max(-30, Math.min(30, Math.round(Math.atan(-4 * height * x / ((count - 1) * step)) * 180 / Math.PI))) };
  };
  const curveCells = (cells, row, direction = 'rtl') => {
    const curvature = row.curvature || 0;
    const height = row.seats.length > 2 ? Math.ceil(Math.abs(curvature) * .48) : 0;
    cells.style.paddingTop = `${curvature < 0 ? height : 0}px`;
    cells.style.paddingBottom = `${curvature > 0 ? height : 0}px`;
    Array.from(cells.children).forEach((cell, index) => {
      const point = curve(curvature, index, row.seats.length);
      cell.style.transform = `translateY(${point.y}px) rotate(${direction === 'rtl' ? -point.angle : point.angle}deg)`;
    });
  };
  window.DidavarVenuePlan = { clone, limits, empty, capacity, positions, build, validateSize, toggle, curve, curveCells };
})();
