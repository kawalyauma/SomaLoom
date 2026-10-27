import type { HTMLAttributes, Attributes } from "react";
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      math: (HTMLAttributes<MathMLElement> & Attributes) & { xmlns?: string; display?: string };
      mrow: (HTMLAttributes<MathMLElement> & Attributes);
      mi: (HTMLAttributes<MathMLElement> & Attributes);
      mn: (HTMLAttributes<MathMLElement> & Attributes);
      mo: (HTMLAttributes<MathMLElement> & Attributes);
      mfrac: (HTMLAttributes<MathMLElement> & Attributes);
      msqrt: (HTMLAttributes<MathMLElement> & Attributes);
      msup: (HTMLAttributes<MathMLElement> & Attributes);
      msub: (HTMLAttributes<MathMLElement> & Attributes);
      mtable: (HTMLAttributes<MathMLElement> & Attributes);
      mtr: (HTMLAttributes<MathMLElement> & Attributes);
      mtd: (HTMLAttributes<MathMLElement> & Attributes);
    }
  }
}
