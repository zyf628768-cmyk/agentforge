(module
  (memory (export "memory") 1 1)
  (func (export "clean") (param $n i32) (result i32)
    (local $i i32) (local $o i32) (local $c i32) (local $pending i32)
    (block $done (loop $loop
      (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
      (local.set $c (i32.load8_u (local.get $i)))
      (if (i32.or (i32.eq (local.get $c) (i32.const 32))
            (i32.and (i32.ge_u (local.get $c) (i32.const 9))
                     (i32.le_u (local.get $c) (i32.const 13))))
        (then (local.set $pending (i32.const 1)))
        (else
          (if (i32.and (local.get $pending) (i32.gt_u (local.get $o) (i32.const 0)))
            (then
              (i32.store8 (i32.add (i32.const 32768) (local.get $o)) (i32.const 32))
              (local.set $o (i32.add (local.get $o) (i32.const 1)))))
          (local.set $pending (i32.const 0))
          ;; VARIANT
          (i32.store8 (i32.add (i32.const 32768) (local.get $o)) (local.get $c))
          (local.set $o (i32.add (local.get $o) (i32.const 1)))))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br $loop)))
    (local.get $o)))
