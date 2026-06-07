FC = /usr/bin/h5pfc.openmpi

INCFLAGS = -I.

LIBFLAGS = -L. 

USE_CUSPARSE = 0

ifeq ($(USE_CUSPARSE),1)
  IF_DEF = -DCUSPARSE
  CC = nvc
  ADDFLAGS = -cudalib=cusparse
  CCFLAGS =  $(ADDFLAGS)
else
  IF_DEF = 
  ADDFLAGS = 
endif

FRTFLAGS = -O3 -march=native $(ADDFLAGS)

OBJS0 = psi_io.o
ifeq ($(USE_CUSPARSE),1)
  OBJS = $(OBJS0) lusol_cusparse.o pot3d.o
else
  OBJS = $(OBJS0) pot3d.o
endif

all: $(OBJS)
	$(FC) $(FRTFLAGS) $(INCFLAGS) $(OBJS) $(LIBFLAGS) -o pot3d
	rm -f *.mod *.modmic *.o 2>/dev/null

install:
	mv pot3d ../bin/

clean:
	rm -f *.mod *.modmic *.o pot3d_cpp.f90 2>/dev/null
	rm -f pot3d 2>/dev/null

pot3d.o: pot3d.F90
	rm -f pot3d_cpp.f90 2>/dev/null
	$(FC) -E -cpp $(IF_DEF) pot3d.F90 > pot3d_cpp.f90
	$(FC) $(FRTFLAGS) $(INCFLAGS) -c pot3d_cpp.f90 -o pot3d.o

psi_io.o: psi_io.f90
	$(FC) $(FRTFLAGS) $(INCFLAGS) -c psi_io.f90 -o psi_io.o

lusol_cusparse.o: lusol_cusparse.c 
	$(CC) $(CCFLAGS) -c lusol_cusparse.c -o lusol_cusparse.o

