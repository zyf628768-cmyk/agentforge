(module
 (memory (export "memory") 1 1)
 (func (export "run") (param $n i32) (result i32)
  (local $i i32) (local $c i32) (local $remaining i32) (local $base i32)
  (block $end (loop $loop
   (br_if $end (i32.ge_u (local.get $i) (local.get $n)))
   (local.set $c (i32.load8_u (local.get $i)))
   (if (local.get $remaining)
    (then
     (if (i32.and (i32.eq (local.get $remaining) (i32.const 1)) (i32.eq (local.get $c) (i32.const 117)))
      (then (local.set $remaining (i32.const 4)))
      (else (local.set $remaining (i32.sub (local.get $remaining) (i32.const 1))))))
    (else
     (if (i32.eq (local.get $c) (i32.const 92)) (then (local.set $remaining (i32.const 1)))
      (else
       (local.set $base (i32.const 0))
       (if (i32.and (i32.ge_u (local.get $c) (i32.const 65)) (i32.le_u (local.get $c) (i32.const 90)))
        (then (local.set $base (i32.const 65))))
       (if (i32.and (i32.ge_u (local.get $c) (i32.const 97)) (i32.le_u (local.get $c) (i32.const 122)))
        (then (local.set $base (i32.const 97))))
       (if (local.get $base)
        (then (local.set $c (i32.add (local.get $base)
          (i32.rem_u (i32.add (i32.sub (local.get $c) (local.get $base)) (i32.const 13)) (i32.const 26))))))))))
   (i32.store8 (i32.add (i32.const 32768) (local.get $i)) (local.get $c))
   (local.set $i (i32.add (local.get $i) (i32.const 1)))
   (br $loop)))
  (local.get $n)))
